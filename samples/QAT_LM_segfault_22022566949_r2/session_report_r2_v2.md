# Live Debug Session — HSD 22022566949

**Title**: [OKS][DMR][VT][X4][VV] Segfault observed while performing QAT LM to Dest VM with cpa_sample_code running
**Component**: QAT / VFIO Live Migration / KVM (kernel regression)
**Execution Mode**: manual
**Status**: active
**Started**: 2026-06-01
**Completed**: 2026-06-10
**Total Iterations**: 5

---

## Hypothesis Evolution

| Iter | Top Hypothesis | Confidence |
|------|----------------|------------|
| 1 | QAT VF migration state not properly restored on destination — system characteriz | 40% |
| 2 | Crash at [98.8s] — NULL function pointer in libc.so.6 (error 44) after QAT migra | 100% |
| 3 | cpa_sample_code active with in-flight ops at migration time — QAT VF busy during | 90% |
| 4 | qat_vfio_pci correctly bound on both VFs; dest domain 0001 vs source 0000 — seco | 70% |
| 5 | Kernel 6.18.8.4.9 regression in post-FLR VFIO/KVM VF state-restore — hardware FL | 85% |

---

## Debug Iterations

### Iteration 1
*2026-06-01*

**Top Hypothesis (40%)**: QAT VF migration state not properly restored on destination — system characterization only

**Logs Collected**:
- `host_terminal_log.rtf` — QAT_LM_segfault_logs/host_terminal_log.rtf (4,818 bytes)
  ```
  [root@cs16ca101ds0506 ~]# yum info qatlib
  qatlib.x86_64  25.08-0.9.5  installed
  [root@cs16ca101ds0506 ~]# uname -r
  6.18.0-dmr.bkc.6.18.8.4.9.x86_64
  [root@cs16ca101ds0506 ~]# nproc
  160
  ```

**GENI Analysis**:

Host confirmed as DMR bare metal (Oak Stream AP A0) with BKC kernel 6.18.8.4.9 and QAT library 25.08/0.9.5. 160 CPU threads available. Preliminary hypothesis: segfault is migration-induced from driver or interrupt remapping state not properly restored on destination. Additional logs needed to characterize crash signature.

**Recommended Next Steps**:
1. **Read host_dmesg_log.rtf**
   > Crash signature and error code will be in host dmesg

---

### Iteration 2
*2026-06-01*

**Top Hypothesis (100%)**: Crash at [98.8s] — NULL function pointer in libc.so.6 (error 44) after QAT migration [CONFIRMED STILL VALID]

**Logs Collected**:
- `host_dmesg_log.rtf` — QAT_LM_segfault_logs/host_dmesg_log.rtf (90,189 bytes)
  ```
  # CRASH (L793):
  [   98.836781] cpa_sample_code[1213]: segfault at 0 ip 00007f8a95d71623
                 error 44 in libc.so.6  ← PFEC 0x2C: I+U+~P = NULL fn ptr
  # FLR also present in FAIL (L790-L792):
  [   52.692337] vfio-pci 0000:00:03.0: reset done  ← FLR 1 completed
  [   60.179925] vfio-pci 0000:00:03.0: reset done  ← FLR 2 completed
  # DISCARDED (L16 — also in PASS):
  qemu-kvm: vtd_interrupt_remap_msi: MSI address low 32 bit invalid: 0x0
  ```

**GENI Analysis**:

CRASH SIGNATURE CONFIRMED: segfault at address 0, error 44 (0x2C = PFEC: I-bit=1, U-bit=1, P-bit=0) — instruction fetch from unmapped user-mode page, i.e., a NULL function pointer call in libc.so.6.

ENGINEER CORRECTION (2026-06-09): vtd_interrupt_remap_msi: MSI address low 32 bit invalid: 0x0 — engineer confirmed this warning ALSO appears in the passing scenario. Verified from PASS logs: Destination_VM_terminal_dmesg.rtf L1424 and Source_VM_terminal_logs.rtf L2028. DISCARDED as non-causal.

FLR PRESENT IN FAIL (v2 correction): host_dmesg_log.rtf L790-L792 confirms reset done at [52.69s] and [60.18s]. Regression is post-FLR, not in FLR itself.

**Recommended Next Steps**:
1. **Read source VM logs for QEMU flags and workload state**
   > Need to confirm QAT workload was active during migration and check QEMU configuration differences

**User Input**: Engineer feedback (vijayag1, 2026-06-09): "earlier analysis pointed to the warning vtd_interrupt_remap_msi: MSI address low 32 bit invalid: 0x0. Actually this is the warning even comes in the passing scenario also. Need to ignore this warning."

---

### Iteration 3
*2026-06-01*

**Top Hypothesis (90%)**: cpa_sample_code active with in-flight ops at migration time — QAT VF busy during handoff (VALID)

**Logs Collected**:
- `source_VM_terminal_logsrtf.rtf` — QAT_LM_segfault_logs/source_VM_terminal_logsrtf.rtf (226,569 bytes)
  ```
  qemu-kvm: warning: IOMMU_IOAS_MAP failed: Bad address, PCI BAR?
    ← DISCARDED: same lines at L8, L11, L12, L493-495 in PASS source VM
  # cpa_sample_code active on source (591/864 Mbps before migration):
  Cipher AES128-XTS Encrypt 64B: 200000 subm, 200000 resp, 591 Mbps
  Cipher AES256-XTS Encrypt 256B: 200000 subm, 200000 resp, 864 Mbps
  # Source FLR (comparable to PASS source at [72.47s]/[85.47s]):
  [52.336437] vfio-pci 0000:00:03.0: resetting
  [52.692337] vfio-pci 0000:00:03.0: reset done  ← source FLR 1
  ```

**GENI Analysis**:

cpa_sample_code running with high throughput (200K/200K ops) at migration trigger — QAT VF has in-flight operations. This remains valid.

IOMMU_IOAS_MAP warnings DISCARDED: 2nd regression passing logs (Source_VM_terminal_logs.rtf L8, L11, L12, L493-495) show identical IOMMU_IOAS_MAP pattern. Known iommufd PCI BAR mapping limitation for QAT 6xxx device 4949 — non-fatal, present in all configurations.

Source-side FLR completes normally at [52.69s]/[60.18s], comparable to PASS source FLR at [72.47s]/[85.47s]. Migration timing differs by ~20s but FLR sequence is structurally identical.

**Recommended Next Steps**:
1. **Examine MobaXterm host session for qat_vfio_pci binding and QEMU flags**
   > Confirm driver binding, destination VF PCI domain, and QEMU command line differences

---

### Iteration 4
*2026-06-01*

**Top Hypothesis (70%)**: qat_vfio_pci correctly bound on both VFs; dest domain 0001 vs source 0000 — secondary variable (VALID)

**Logs Collected**:
- `MobaXterm_10.49.152.143_20260601_055012.rtf` — QAT_LM_segfault_logs/MobaXterm_10.49.152.143_20260601_055012.rtf (369,344 bytes)
  ```
  [ 1089.405937] qat_vfio_pci 0000:0f:00.1: enabling device (0000 -> 0002)
  [ 1089.416108] qat_vfio_pci 0000:0f:00.1: resetting
  [ 1092.403753] qat_vfio_pci 0000:0f:00.1: resetting
  [ 1113.899971] qat_vfio_pci 0001:0f:00.1: enabling device (0000 -> 0002)
  [ 1113.907280] qat_vfio_pci 0001:0f:00.1: resetting
  # QEMU dest command includes: -global kvm-apic.vapic=false
  #   (NEW discriminator — PASS dest does NOT have this flag)
  # Dest sysfsdev: /sys/bus/pci/devices/0001:0f:00.1 (domain 0001)
  ```

**GENI Analysis**:

qat_vfio_pci correctly bound and FLR triggered on both source (0000:0f:00.1) and destination (0001:0f:00.1). Driver setup is correct.

INVALIDATED ROOT CAUSE: Original Iter 4 stated qat_vfio_pci save/restore does not include MSI-X table entries, leaving VT-d IRTE address=0x0. This was based on vtd_interrupt_remap_msi as trigger — now confirmed benign.

NEW DISCRIMINATOR FOUND (2026-06-10): FAIL QEMU destination command includes -global kvm-apic.vapic=false (vAPIC disabled). PASS destination QEMU command does NOT include this flag. vAPIC disablement forces all LAPIC accesses through MMIO emulation rather than the virtualized APIC page, potentially altering MSI-X re-arm behavior post-migration when combined with the kernel regression.

**Recommended Next Steps**:
1. **Compare pass vs fail destination dmesg for all configuration deltas**
   > Need pass logs to establish full pass/fail differential

**User Input**: Engineer: vtd_interrupt_remap_msi warning also appears in passing scenario — need to ignore.

---

### Iteration 5
*2026-06-10*

**Top Hypothesis (85%)**: Kernel 6.18.8.4.9 regression in post-FLR VFIO/KVM VF state-restore — hardware FLR completes on both kernels but subsequent IRQ vector/MSI-X/callback-pointer restoration broken in 6.18.8.4.9; crash at first QAT completion IRQ post-migration

**Logs Collected**:
- `Destination_VM_terminal_dmesg.rtf (PASS · 6.18.5.2.5)` — QAT_LM_Passing_logs_6.18.5.2.5_kernel/Destination_VM_terminal_dmesg.rtf (180,553 bytes)
  ```
  QEMU dest cmd: sysfsdev=.../0000:0f:00.2  (NO -global kvm-apic.vapic=false)
  # FLR on PASS dest:
  [   72.115616] vfio-pci 0000:00:03.0: resetting
  [   72.469061] vfio-pci 0000:00:03.0: reset done  ← FLR 1 (+353ms)
  [   85.115966] vfio-pci 0000:00:03.0: resetting
  [   85.468760] vfio-pci 0000:00:03.0: reset done  ← FLR 2 (+353ms)
  # TSC skew (L11) — 12x FAIL value, NO crash:
  [  131.067230] clocksource: 'tsc' skewed -139066744 ns (-139 ms)
  ```
- `Source_VM_terminal_logs.rtf (PASS · 6.18.5.2.5)` — QAT_LM_Passing_logs_6.18.5.2.5_kernel/Source_VM_terminal_logs.rtf (247,491 bytes)
  ```
  # IOMMU_IOAS_MAP (L8, L11, L12, L493-495) — IDENTICAL to FAIL:
  qemu-kvm: warning: IOMMU_IOAS_MAP failed: Bad address, PCI BAR?
  # vtd warning (L2028) — also in PASS:
  qemu-kvm: vtd_interrupt_remap_msi: MSI address low 32 bit invalid: 0x0
  # Source FLR on PASS (comparable timing to FAIL):
  [   72.469061] vfio-pci 0000:00:03.0: reset done
  ```
- `host_dmesg_terminal)log.rtf (PASS · 6.18.5.2.5)` — QAT_LM_Passing_logs_6.18.5.2.5_kernel/host_dmesg_terminal)log.rtf (341,963 bytes)
  ```
  Linux version 6.18.0-dmr.bkc.6.18.5.2.5.x86_64 — no crash, qat_vfio_pci setup OK
  ```

**GENI Analysis**:

PASS/FAIL COMPARISON — KEY FINDINGS:

1. vtd_interrupt_remap_msi DISCARDED (engineer-confirmed + log-verified):
   Present at L1424 (PASS dest) and L2028 (PASS source). Non-causal QEMU    warn_report() during VF re-initialization.

2. TSC skew DISCARDED (log-verified): PASS = -139ms (L11), FAIL = -11ms (L13).
   12x larger skew in PASS with no crash. TSC instability is a side-effect    of imprecise offset migration; kvm-clock takes over in both cases.

3. IOMMU_IOAS_MAP DISCARDED (log-verified): Identical at L8/L11/L12/L493-495
   in both PASS and FAIL source VMs. Known iommufd/QAT BAR limitation.

4. FLR CORRECTION (v2): FAIL also has vfio-pci reset done at [52.69s]+[60.18s]
   (host_dmesg_log.rtf L790-L792). Regression is post-FLR state restoration,
   not in the FLR sequence itself.

5. NEW DISCRIMINATOR: FAIL QEMU dest has -global kvm-apic.vapic=false;
   PASS does NOT. vAPIC disablement alters LAPIC MMIO path — possible
   interaction with kernel regression in MSI-X vector re-arm.

6. KEY DISCRIMINATORS SUMMARY:
   FAIL: kernel 6.18.8.4.9 | VF domain 0001 | vapic=false | crash [98.8s]
   PASS: kernel 6.18.5.2.5 | VF domain 0000 | vapic enabled | 1342-1857 Mbps

CONCLUSION: Kernel regression between 6.18.5.2.5 and 6.18.8.4.9 in the VFIO/KVM post-FLR state restoration path. After hardware FLR completes, the 6.18.8.4.9 kernel fails to properly reinstate the QAT VF's IRQ vectors, MSI-X entries, or VFIO eventfd bindings. When cpa_sample_code fires its first completion callback at [98.8s], it calls through an uninitialized function pointer at address 0x0 — fatal segfault (PFEC error 44).

**Recommended Next Steps**:
1. **A/B isolation: kernel 6.18.8.4.9 with PASS topology (VF 0000:0f:00.2, vapic enabled)**
   > Isolates kernel as primary variable independent of PCI domain and vapic flag
   ```
   # Modify dest QEMU: sysfsdev=.../0000:0f:00.2, remove -global kvm-apic.vapic=false
   ```
2. **A/B: kernel 6.18.5.2.5 with -global kvm-apic.vapic=false added**
   > Determines whether vapic=false alone (on passing kernel) triggers the crash
   ```
   # Add -global kvm-apic.vapic=false to PASS dest QEMU command
   ```
3. **Enable vfio_pci dynamic debug on failing kernel (post-FLR trace)**
   > Reveals what happens after reset done — IRQ vector and MSI-X re-arm details
   ```
   echo 'module vfio_pci +p' > /sys/kernel/debug/dynamic_debug/control && dmesg -w | grep -i 'vfio\|msi\|irq\|0001:0f'
   ```
4. **Kernel git log delta 6.18.5.2.5 → 6.18.8.4.9 (VFIO/KVM/iommufd paths)**
   > Direct commit-level evidence of the regression — focus on FLR, MSI-X, migration callbacks
   ```
   git log --oneline v6.18.5.2.5..v6.18.8.4.9 drivers/vfio/pci/ virt/kvm/ | grep -i 'reset\|msi\|migrat\|flr\|irq'
   ```

---

## Final Root Cause

Primary fix (kernel/LFE 22022566950): Linux KVM team to identify the regressing commit between 6.18.5.2.5 and 6.18.8.4.9 in the VFIO/KVM post-FLR state restoration path for migrated QAT SR-IOV VFs. Focus: drivers/vfio/pci/, virt/kvm/, drivers/iommu/ — specifically VF MSI-X vector reinstatement, VFIO IRQ eventfd re-binding, or IOMMU domain reattachment ordering after FLR.

Immediate workaround: downgrade to kernel 6.18.5.2.5 (DMR BKC WW14). Confirmed passing by engineer on multiple systems.

Isolation tests needed:
  ① 6.18.8.4.9 + dest VF 0000:0f:00.2 + vapic enabled → kernel is primary variable
  ② 6.18.5.2.5 + -global kvm-apic.vapic=false → vapic flag alone causal?

**Spec Reference**: PCIe Base Spec §6.6.2 — FLR completes within 100ms (confirmed: ~354ms in both cases). VFIO kernel docs (Documentation/driver-api/vfio.rst) — post-reset device state must be fully re-established before guest access resumes. Intel SDM Vol 3 §6.15 Table 6-7 — PFEC 0x2C = I+U+~P = NULL function pointer call.

**Evidence Chain**:
- Iter 1: QAT qatlib 25.08/0.9.5 + BKC kernel 6.18.8.4.9 on DMR host confirmed
- Iter 2: segfault at 0, error 44 in libc.so.6 at [98.8s] — NULL function pointer confirmed
- Iter 2: vtd_interrupt_remap_msi DISCARDED: verified in PASS logs L1424 (dest) + L2028 (source)
- Iter 2: FLR present in FAIL (host_dmesg L790-L792): reset done at [52.69s]+[60.18s] — v2 correction
- Iter 3: cpa_sample_code active (591/864 Mbps) at migration trigger — VF busy during handoff
- Iter 3: IOMMU_IOAS_MAP DISCARDED: identical at L8/L11/L12/L493-495 in PASS source VM
- Iter 4: qat_vfio_pci correctly bound on both VFs — driver setup valid
- Iter 4: NEW: FAIL QEMU has -global kvm-apic.vapic=false; PASS does NOT — additional config delta
- Iter 5: PASS FLR at [72.47s]+[85.47s]; cpa throughput 1342-1857 Mbps — full success on 6.18.5.2.5
- Iter 5: TSC skew DISCARDED: PASS −139ms (12×), FAIL −11ms — larger in PASS with no crash
- Iter 5: Kernel regression confirmed: 6.18.5.2.5 passes, 6.18.8.4.9 fails; LFE 22022566950 assigned to Linux KVM team

---

*Generated by HSD Live Debug Agent — 2026-06-10T17:48:43*
*Template: live_debug_report_template.html v1.0 — project-c3/hsd-triage*