#!/usr/bin/env python3
"""
DMR IERR Reproduction Script — HSD 15018590736
================================================
Repro: Run stressapptest, then idle system for 4+ hours.
Observe: IERR assertion / system hang after idle period.

Repro steps from HSD (no diagnosis/root cause used):
  1. Run Stressapptest
  2. Idle system over 4 hours
  3. System hang / IERR flag observed

VALOR-aware: emits VERDICT: PASS/FAIL/INCONCLUSIVE lines.
Evidence is pre-collected before stress to survive a potential system hang.
"""

import subprocess
import sys
import os
import re
import time
import datetime
import signal
import threading

LOG_DIR = os.environ.get("VALOR_LOG_DIR", "/tmp/valor_logs")
os.makedirs(LOG_DIR, exist_ok=True)

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
EVIDENCE_FILE = f"{LOG_DIR}/ierr_evidence_{TIMESTAMP}.txt"

# Configurable: allow shorter wait for CI/quick-run
STRESS_DURATION_MIN = int(os.environ.get("STRESS_DURATION_MIN", "30"))
IDLE_WAIT_HOURS = float(os.environ.get("IDLE_WAIT_HOURS", "4"))
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "300"))  # check every 5 min

print(f"[CONFIG] Stress duration: {STRESS_DURATION_MIN} min, Idle wait: {IDLE_WAIT_HOURS} hr")


def run(cmd, timeout=30, shell=True):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {timeout}s]"
    except Exception as e:
        return f"[ERROR: {e}]"


def section(title, content, f):
    banner = f"\n{'='*70}\n=== {title}\n{'='*70}\n"
    print(banner)
    f.write(banner)
    print(str(content)[:3000])
    f.write(str(content)[:3000] + "\n")


def collect_system_state(label):
    """
    Collect all key system state that would be relevant to diagnose
    a CPU IERR / system hang. Collected before and after stress.
    Survives system hang by writing to disk immediately.
    """
    state = {}
    state["dmesg_tail"]     = run("dmesg | tail -50")
    state["dmesg_errors"]   = run("dmesg | grep -iE 'mce|mca|ierr|caterr|error|fail|hang|panic|warn' | tail -50")
    state["mcelog"]         = run("mcelog --client 2>/dev/null | tail -30; true")
    state["sel_log"]        = run("ipmitool sel list 2>/dev/null | tail -20 || echo 'ipmitool N/A'")
    state["mce_count"]      = run("grep -c '' /var/log/mcelog 2>/dev/null || echo '0'")
    state["cpu_idle_state"] = run("cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name 2>/dev/null | head -10")
    state["cpu_freq"]       = run("cpupower frequency-info 2>/dev/null | grep -E 'current|min|max' | head -5; "
                                  "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null")
    state["cpupower_idle"]  = run("cpupower idle-info 2>/dev/null | head -20 || cat /proc/acpi/info 2>/dev/null | head -10")
    state["loadavg"]        = run("uptime; cat /proc/loadavg")
    state["edac_ce"]        = run("cat /sys/devices/system/edac/mc/mc*/ce_count 2>/dev/null || echo 'edac N/A'")
    state["edac_ue"]        = run("cat /sys/devices/system/edac/mc/mc*/ue_count 2>/dev/null || echo 'edac N/A'")
    state["mcg_status"]     = run("rdmsr 0x17A 2>/dev/null || echo 'rdmsr N/A'")
    state["msr_mperf"]      = run("rdmsr 0xE8 2>/dev/null || echo 'N/A'")  # MPERF
    state["msr_aperf"]      = run("rdmsr 0xE7 2>/dev/null || echo 'N/A'")  # APERF
    state["power_state"]    = run("cat /sys/class/power_supply/*/status 2>/dev/null; "
                                  "cat /sys/firmware/acpi/interrupts/sci 2>/dev/null | head -5")
    state["interrupts_snap"] = run("head -3 /proc/interrupts; grep -E 'MCE|NMI|TLB|MCI' /proc/interrupts | head -5")
    state["journalctl_errs"] = run("journalctl -k -p err..alert --since='30 minutes ago' 2>/dev/null | tail -30")

    # Write snapshot to disk immediately (survives hang)
    snap_file = f"{LOG_DIR}/snap_{label}_{TIMESTAMP}.txt"
    with open(snap_file, "w") as sf:
        for k, v in state.items():
            sf.write(f"\n=== {k} ===\n{v}\n")
    print(f"[snapshot] Written: {snap_file}")

    return state


def check_ierr_present(state):
    """
    Look for IERR/CATERR/system hang indicators in collected state.
    Pure observation — no interpretation of root cause.
    """
    signals = {
        "ierr_in_dmesg": False,
        "caterr_in_dmesg": False,
        "mce_fatal_in_dmesg": False,
        "new_sel_entries": False,
        "new_mce_count": False,
        "raw_matches": [],
    }

    all_text = state.get("dmesg_errors", "") + state.get("sel_log", "") + state.get("mcelog", "")

    if re.search(r'\bierr\b', all_text, re.I):
        signals["ierr_in_dmesg"] = True
    if re.search(r'\bcaterr\b|\bcat_err\b', all_text, re.I):
        signals["caterr_in_dmesg"] = True
    if re.search(r'machine check.*fatal|mce.*fatal|fatal.*mce', all_text, re.I):
        signals["mce_fatal_in_dmesg"] = True

    for line in all_text.splitlines():
        if re.search(r'ierr|caterr|machine.*check.*fatal|panic|hung.*task|rcu.*stall', line, re.I):
            signals["raw_matches"].append(line.strip())

    return signals


def run_stressapptest():
    """Run stressapptest — standard memory + CPU stress tool."""
    print(f"\n[STRESS] Starting stressapptest for {STRESS_DURATION_MIN} minutes...")
    
    # Find stressapptest binary
    sat_bin = run("which stressapptest 2>/dev/null || which sat_lite 2>/dev/null").strip()
    if not sat_bin or sat_bin.startswith("["):
        # Try install
        run("dnf install -y stressapptest 2>/dev/null", timeout=120)
        sat_bin = run("which stressapptest 2>/dev/null").strip()
    
    if not sat_bin or sat_bin.startswith("["):
        return False, "stressapptest not found and could not be installed"

    # Available memory (use 80%)
    mem_kb = run("grep MemAvailable /proc/meminfo | awk '{print $2}'").strip()
    try:
        mem_mb = int(int(mem_kb) * 0.8 / 1024)
    except Exception:
        mem_mb = 8192

    # Number of CPUs
    cpu_count = int(run("nproc").strip() or "8")

    cmd = (
        f"{sat_bin} "
        f"-s {STRESS_DURATION_MIN * 60} "   # seconds
        f"-M {mem_mb} "                      # memory in MB
        f"-C {cpu_count} "                   # CPU threads
        f"-W "                               # use warm-up
        f"-l {LOG_DIR}/stressapptest_{TIMESTAMP}.log"
    )
    print(f"[STRESS] Command: {cmd}")

    start = time.time()
    result = run(cmd, timeout=(STRESS_DURATION_MIN * 60) + 60)
    elapsed = time.time() - start

    print(f"[STRESS] Completed in {elapsed:.0f}s")
    print(f"[STRESS] Output tail:\n{result[-500:]}")

    passed = "Status: PASS" in result or elapsed >= (STRESS_DURATION_MIN * 60 - 10)
    return passed, result


def monitor_idle(pre_signals, evidence_file):
    """
    Monitor the system during idle phase.
    Polls every POLL_INTERVAL_SEC for IERR indicators.
    Returns True if IERR detected.
    """
    idle_end = time.time() + (IDLE_WAIT_HOURS * 3600)
    poll_num = 0

    print(f"\n[IDLE] Entering idle phase — monitoring for {IDLE_WAIT_HOURS} hours")
    print(f"[IDLE] Will poll every {POLL_INTERVAL_SEC}s. Press Ctrl+C to abort.\n")

    with open(evidence_file, "a") as f:
        while time.time() < idle_end:
            poll_num += 1
            elapsed_min = (poll_num * POLL_INTERVAL_SEC) / 60
            remaining_hr = (idle_end - time.time()) / 3600
            print(f"[IDLE] Poll {poll_num} — {elapsed_min:.0f} min elapsed, {remaining_hr:.1f} hr remaining")

            snap = collect_system_state(f"idle_poll_{poll_num:03d}")
            signals = check_ierr_present(snap)

            section(f"IDLE POLL {poll_num} ({elapsed_min:.0f} min)", str(signals), f)

            if signals["ierr_in_dmesg"] or signals["caterr_in_dmesg"] or signals["mce_fatal_in_dmesg"]:
                print(f"\n[!] IERR/CATERR DETECTED at poll {poll_num}!")
                print(f"    Signals: {signals['raw_matches'][:5]}")
                f.write(f"\n[!] IERR/CATERR DETECTED at poll {poll_num}!\n")
                f.write(f"    Matches: {signals['raw_matches']}\n")
                return True, snap

            time.sleep(POLL_INTERVAL_SEC)

    return False, None


def main():
    print(f"\n{'#'*70}")
    print(f"# DMR IERR Reproduction — VALOR Test Runner")
    print(f"# Repro: Run stressapptest → idle {IDLE_WAIT_HOURS}h → observe IERR")
    print(f"# {datetime.datetime.now().isoformat()}")
    print(f"{'#'*70}\n")

    with open(EVIDENCE_FILE, "w") as f:
        f.write(f"DMR IERR Repro Evidence — {datetime.datetime.now().isoformat()}\n")

    # ── PRE-STRESS: Full system snapshot ─────────────────────────────────────
    print("[STEP 1] Pre-stress system snapshot...")
    pre_state = collect_system_state("pre_stress")
    pre_signals = check_ierr_present(pre_state)

    with open(EVIDENCE_FILE, "a") as f:
        section("PRE-STRESS STATE", str(pre_state), f)
        section("PRE-STRESS SIGNALS", str(pre_signals), f)

    # ── RUN STRESSAPPTEST ─────────────────────────────────────────────────────
    print("\n[STEP 2] Running stressapptest...")
    sat_ok, sat_output = run_stressapptest()

    with open(EVIDENCE_FILE, "a") as f:
        section("STRESSAPPTEST OUTPUT", sat_output[:3000], f)
        section("STRESSAPPTEST STATUS", f"Passed: {sat_ok}", f)

    # ── POST-STRESS SNAPSHOT (before idle) ───────────────────────────────────
    print("\n[STEP 3] Post-stress snapshot (before idle)...")
    post_stress_state = collect_system_state("post_stress")

    with open(EVIDENCE_FILE, "a") as f:
        section("POST-STRESS STATE", str(post_stress_state), f)

    # ── IDLE MONITORING PHASE ────────────────────────────────────────────────
    print("\n[STEP 4] Entering idle monitoring phase...")
    ierr_detected, ierr_snap = monitor_idle(pre_signals, EVIDENCE_FILE)

    # ── FINAL SNAPSHOT ────────────────────────────────────────────────────────
    print("\n[STEP 5] Final system snapshot...")
    final_state = collect_system_state("final")
    final_signals = check_ierr_present(final_state)

    with open(EVIDENCE_FILE, "a") as f:
        section("FINAL STATE", str(final_state), f)
        section("FINAL SIGNALS", str(final_signals), f)

        # Full dmesg for BugScout
        full_dmesg = run("dmesg 2>/dev/null | tail -300")
        section("FULL DMESG (last 300 lines)", full_dmesg, f)

        full_journal = run("journalctl -k --since='6 hours ago' 2>/dev/null | tail -200")
        section("FULL JOURNAL (6h)", full_journal, f)

        sel_full = run("ipmitool sel list 2>/dev/null | tail -50 || echo 'ipmitool N/A'")
        section("IPMI SEL (full)", sel_full, f)

    # ── VERDICT ──────────────────────────────────────────────────────────────
    print("\n[STEP 6] Verdict...")

    if ierr_detected or final_signals["ierr_in_dmesg"] or final_signals["caterr_in_dmesg"]:
        result = "FAIL: IERR/CATERR detected after stressapptest idle period"
        verdict = "VERDICT: FAIL"
    elif not sat_ok:
        result = "INCONCLUSIVE: stressapptest did not complete successfully"
        verdict = "VERDICT: INCONCLUSIVE"
    else:
        result = f"PASS: No IERR detected after {IDLE_WAIT_HOURS}h idle (issue may need longer idle or different config)"
        verdict = "VERDICT: PASS"

    print(f"\n{result}")
    print(verdict)

    with open(EVIDENCE_FILE, "a") as f:
        f.write(f"\n{result}\n{verdict}\n")
        f.write(f"\nEvidence: {EVIDENCE_FILE}\n")
        f.write(f"Snapshots: {LOG_DIR}/snap_*_{TIMESTAMP}.txt\n")

    print(f"\n[DONE] Evidence: {EVIDENCE_FILE}")
    return 1 if "FAIL" in verdict else 0


if __name__ == "__main__":
    sys.exit(main())
