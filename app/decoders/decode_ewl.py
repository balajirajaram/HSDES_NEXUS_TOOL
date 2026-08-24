#!/usr/bin/env python3
"""
EWL Log Decoder - Parse BIOS logs and decode error codes

Extracts Enhanced Warning Log codes from BIOS logs and provides code meanings from EWL spec.

@copyright
INTEL CONFIDENTIAL
Copyright (C) 2026 Intel Corporation.
"""

import re
import json
import sys
import os
from pathlib import Path
from collections import defaultdict

# Add shared utilities to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from decoder_utils import load_json_database, resolve_db_path
from decode_mcheck import McheckDecoder


class EWLDecoder:
    """Decoder for Enhanced Warning Log codes"""

    _IPSD_DB_PATH = Path(__file__).parent / "ipsd_codes_database.json"

    # Known-expected or informational messages that commonly look like errors.
    # Each tuple: (compiled_regex, label_key, explanation_string)
    # When a log line matches, it is collected as type='BENIGN' rather than left unclassified.
    _KNOWN_BENIGN_PATTERNS = [
        (
            re.compile(r'\[IPMI\].*BMC does not respond.*Device Error', re.IGNORECASE),
            'bmc_retry',
            'BMC communication retry — BMC temporarily unresponsive; usually correlates with '
            'the IPSD C80000002 ("Device Error") code. Not a BIOS bug if BMC eventually responds.',
        ),
        (
            re.compile(r'IioUbaLoadSwGpioBifurcation.*Can not decode given bif\. code', re.IGNORECASE),
            'iio_bif_unknown',
            'IIO PCIe bifurcation code unrecognized — expected on unpopulated PCIe slots or on '
            'alpha/reference boards where the FPGA reports code 0 (no device) or an unregistered '
            'bifurcation value. BIOS skips the slot; no functional impact.',
        ),
        (
            re.compile(r'Tpm2RegisterTpm2DeviceLib\s+-\s+does not support', re.IGNORECASE),
            'tpm2_no_device',
            'TPM2 device library registration skipped — a TPM2 driver instance was not recognized. '
            'Expected when no physical TPM2 chip is present or TPM is disabled in setup.',
        ),
        (
            re.compile(r'SPD FFS:.*No more volumes.*couldn.{0,5}t find SPD FFS file', re.IGNORECASE),
            'spd_ffs_missing',
            'SPD FFS override file not found in firmware volumes — expected when no bundled SPD '
            'override FFS is included. BIOS falls back to reading SPD data from physical DIMMs.',
        ),
        (
            re.compile(r'LT_ERROR_CODE\[0x[0-9A-Fa-f]+\]\s*=\s*0x', re.IGNORECASE),
            'lt_error_code_dump',
            'BootGuard ACM status register (LT_BIOSACMCode) diagnostic dump from '
            'IsBootGuardSupported(). The ACM error code field (bits [14:4]) should be 0 on '
            'a clean boot. Value 0x0000000000830000 has error field = 0 — no error.',
        ),
        (
            re.compile(r'StackCap=0.*Not support CXL', re.IGNORECASE),
            'cxl_stack_no_cap',
            'IIO PCIe stack reports no CXL capability (StackCap=0) — expected when no CXL device '
            'is installed on that port. Logged by IioCxlSpecific.c; BIOS disables CXL on the stack.',
        ),
        (
            re.compile(r'IpHiopIpInit.*IP_ID_3.*!=.*IP_ID_3_DEFAULT', re.IGNORECASE),
            'ip_id_mismatch',
            'IMH HIOP IP version mismatch — IP_ID_3 register differs from compile-time default. '
            'The firmware log itself says "it is expected, but not guaranteed, to be compatible." '
            'Common on pre-production/alpha silicon with a newer RTL build than BIOS was '
            'compiled against. Not a blocking error unless IP features fail.',
        ),
        (
            re.compile(r'IpEipPcieEnableSlotsPower.*VPP error.*ShpcErrSts=', re.IGNORECASE),
            'pcie_vpp_error',
            'PCIe slot VPP (voltage/power) enable error — hot-plug power controller reported a '
            'fault (ShpcErrSts=0x1). Expected for unpopulated or uncabled PCIe hot-plug slots; '
            'BIOS continues initialization for other slots.',
        ),
        (
            re.compile(r'IpCxlcm.*_LinkPowerManagementSetControl.*Incorrect IpTarget=0', re.IGNORECASE),
            'cxl_no_target',
            'CXL port link power management called with no valid device target (IpTarget=0) — '
            'expected when no CXL device is installed on the port. BIOS returns an error '
            'internally but continues.',
        ),
        (
            re.compile(r'IpMcGetShadowMca\s*\(\s*\).*NOTIFY.*ErrorRecord is not valid', re.IGNORECASE),
            'shadow_mca_empty',
            'MC shadow MCA area has no stored error record — expected on clean boots with no '
            'previous machine check event. BIOS skips shadow MCA error recovery for this sub-channel.',
        ),
        (
            re.compile(r'IpMcGetShadowMca failed Node', re.IGNORECASE),
            'shadow_mca_empty',
            'MC shadow MCA lookup found no prior error — expected on a clean boot with no '
            'previous machine check stored in the shadow area.',
        ),
        (
            re.compile(r'IpCxlcm.*WARN.*IpCxlcmIpInit.*IpId[23]=.*not guaranteed to be compatible', re.IGNORECASE),
            'cxlcm_ip_id_mismatch',
            'CXL CM IP version mismatch — IpId2/IpId3 registers differ from expected values; '
            'log says "not guaranteed to be compatible." Normal on alpha/pre-production silicon '
            'where the RTL stepping is newer than the BIOS compilation target.',
        ),
        (
            re.compile(r'IpicmGetIpInstance.*IP Instance.*has not been created', re.IGNORECASE),
            'ip_instance_not_created',
            'IP connectivity manager reports an instance as not yet created — informational '
            'message emitted when accessing an IP before its initialization completes. '
            'Expected during early DXE boot flow.',
        ),
        (
            re.compile(r'\[SGX-LATE-PRE-MCHECK\].*SgxLatePreMcheck_EnableFlow.*Unsupported', re.IGNORECASE),
            'sgx_premcheck_unsupported',
            'SGX pre-MCHECK initialization returned EFI_UNSUPPORTED — expected when SGX is '
            'not enabled in setup or the platform does not support SGX. Printed at '
            'SECURITY_D_ERROR level but indicates a disabled feature, not a failure.',
        ),
    ]

    def __init__(self, db_path=None, rc_db_path=None):
        """Initialize decoder with code databases."""
        # Use script directory as default if paths not provided
        script_dir = Path(__file__).parent
        
        if db_path is None:
            db_path = script_dir / 'ewl_codes_database.json'
        else:
            db_path = Path(db_path)
            # If relative path, make it relative to script directory
            if not db_path.is_absolute() and not db_path.exists():
                alt_path = script_dir / db_path
                if alt_path.exists():
                    db_path = alt_path
        
        if rc_db_path is None:
            rc_db_path = script_dir / 'rc_fatal_errors_database.json'
        else:
            rc_db_path = Path(rc_db_path)
            # If relative path, make it relative to script directory
            if not rc_db_path.is_absolute() and not rc_db_path.exists():
                alt_path = script_dir / rc_db_path
                if alt_path.exists():
                    rc_db_path = alt_path
        
        self.db = self.load_database(str(db_path))
        self.rc_db = self.load_database(str(rc_db_path))

        ipsd_raw = load_json_database(self._IPSD_DB_PATH, default={})
        self.IPSD_ERRORS = {int(k, 16): v["description"] for k, v in ipsd_raw.items()} if ipsd_raw else {}

        self.mcheck_decoder = McheckDecoder()

        if self.db:
            print(f"✓ Loaded {len(self.db)} EWL codes from database", file=sys.stderr)
        if self.rc_db:
            real_majors = {k: v for k, v in self.rc_db.items() if k != '__generic__'}
            total_rc_minors = sum(len(v.get('minors', {})) for v in real_majors.values())
            generic_count = len(self.rc_db.get('__generic__', {}).get('minors', {}))
            print(f"✓ Loaded {len(real_majors)} RC fatal major codes ({total_rc_minors} minors, "
                  f"+{generic_count} generic) from database", file=sys.stderr)
    
    def load_database(self, path):
        """Load JSON database file."""
        return load_json_database(path, default=None)
    
    def decode_code(self, major_code, minor_code=None):
        """
        Decode error/warning codes and return information.
        
        Returns dict with: code, name, description
        """
        result = {
            'major_code': major_code,
            'minor_code': minor_code,
            'major_name': None,
            'minor_name': None,
            'major_desc': None,
            'minor_desc': None
        }
        
        # Lookup codes in database (majors at top level, minors nested under majors)
        if self.db:
            major_info = self.db.get(major_code.lower())  # DB uses lowercase
            if major_info and major_info.get('type') == 'major':
                result['major_name'] = major_info.get('name')
                result['major_desc'] = major_info.get('description')
                
                # Look for minor code under this major
                if minor_code:
                    minors = major_info.get('minors', {})
                    minor_info = minors.get(minor_code.lower())
                    if minor_info:
                        result['minor_name'] = minor_info.get('name')
                        result['minor_desc'] = minor_info.get('description')
        
        return result
    
    def decode_rc_fatal_error(self, major_code, minor_code=None, mmc_origin=False):
        """
        Decode RC (Reference Code) fatal error codes.
        
        Args:
            major_code: Major error code (e.g., '0xCD')
            minor_code: Minor error code (e.g., '0x30')
            mmc_origin: True when the error originates from MMC on-die firmware.
                        Enables fallback to __generic__ minor codes for ERR_RC_INTERNAL
                        (0xF2), which uses RC_FATAL_ERROR_MINOR_CODE_N values that
                        have no explicit major association in the header.
        
        Returns:
            dict with: major_code, minor_code, major_name, minor_name, descriptions, source
        """
        result = {
            'major_code': major_code,
            'minor_code': minor_code,
            'major_name': None,
            'minor_name': None,
            'major_desc': None,
            'minor_desc': None,
            'major_source': None,
            'minor_source': None
        }
        
        # Lookup codes in RC database (majors at top level, minors nested)
        if self.rc_db:
            major_info = self.rc_db.get(major_code.lower())
            if major_info and major_info.get('type') == 'major':
                result['major_name'] = major_info.get('name')
                result['major_desc'] = major_info.get('description')
                result['major_source'] = major_info.get('source')
                
                # Look for minor code under this major
                if minor_code:
                    minors = major_info.get('minors', {})
                    minor_info = minors.get(minor_code.lower())

                    # For MMC-origin errors, fall back when the major-specific dict has no
                    # entry for this minor.  The fallback order matters:
                    #   1. For ERR_RC_INTERNAL (0xF2): check SPD minor codes first
                    #      (SPD_FATAL_ERROR_READ_MINOR_CODE_* from major 0x06 /
                    #      ERR_INVALID_READ_REG_SIZE).  The MMC firmware raises ERR_RC_INTERNAL
                    #      with SPD minor enum values — e.g. 0x19 =
                    #      SPD_FATAL_ERROR_READ_MINOR_CODE_025 (ManufacturerId - SPD read Byte
                    #      failed), not RC_FATAL_ERROR_MINOR_CODE_25 (GetSetClkPieOffset).
                    #   2. All other majors: fall back to __generic__
                    #      (RC_FATAL_ERROR_MINOR_CODE_N values).
                    if minor_info is None and mmc_origin:
                        if major_code.lower() == '0xf2':
                            spd_minors = self.rc_db.get('0x06', {}).get('minors', {})
                            minor_info = spd_minors.get(minor_code.lower())
                        if minor_info is None:
                            generic_minors = self.rc_db.get('__generic__', {}).get('minors', {})
                            minor_info = generic_minors.get(minor_code.lower())

                    if minor_info:
                        result['minor_name'] = minor_info.get('name')
                        result['minor_desc'] = minor_info.get('description')
                        result['minor_source'] = minor_info.get('source')
        
        return result
    
    def decode_error_code(self, error_code):
        """
        Decode combined error code format (e.g., 0x3000CD2C).
        
        Format appears to be:
        - Bits 31-16: Context/flags (0x3000)
        - Bits 15-8:  Major error code (0xCD)
        - Bits 7-0:   Minor error code (0x2C)
        
        Args:
            error_code: Combined error code as string or integer
        
        Returns:
            dict with: major_code, minor_code, context, decoded_info
        """
        # Convert to integer if string
        if isinstance(error_code, str):
            if error_code.upper().startswith('0X'):
                error_val = int(error_code, 16)
            else:
                error_val = int(error_code, 0)
        else:
            error_val = error_code
        
        # Extract fields
        context = (error_val >> 16) & 0xFFFF
        major = (error_val >> 8) & 0xFF
        minor = error_val & 0xFF

        major_hex = f"0x{major:02X}"
        minor_hex = f"0x{minor:02X}"

        # Decode using RC fatal error decoder
        decoded = self.decode_rc_fatal_error(major_hex, minor_hex)

        return {
            'error_code': f"0x{error_val:08X}",
            'context': f"0x{context:04X}",
            'major_code': major_hex,
            'minor_code': minor_hex,
            'decoded': decoded
        }
    
    def decode_ipsd_error(self, error_code):
        """
        Decode IPSD (Intel Platform Service Provider) error code.
        
        Args:
            error_code: String like "C80000002" or integer
        
        Returns:
            dict with code and description
        """
        if isinstance(error_code, str):
            # Remove 'C' prefix if present
            if error_code.upper().startswith('C'):
                error_code = error_code[1:]
            error_val = int(error_code, 16)
        else:
            error_val = error_code
        
        description = self.IPSD_ERRORS.get(error_val, "Unknown IPSD Error")
        
        return {
            'code': f"0x{error_val:08X}",
            'description': description,
            'type': 'IPSD'
        }
    
    def parse_log(self, log_text):
        """
        Parse log text and extract all error codes with context.

        Returns list of dicts with type in {'EWL', 'IPSD', 'RC_FATAL', 'MMC_STATUS'} plus
        relevant fields (major, minor, socket, context, file_ref, mmc_source, ...).
        """
        codes = []

        # Pattern 1: "Major Warning Code = 0xNN, Minor Warning Code = 0xNN"
        pattern1 = r'Major Warning Code\s*=\s*(0x[0-9A-Fa-f]+).*?Minor Warning Code\s*=\s*(0x[0-9A-Fa-f]+)'

        # Pattern 2: "Error Logged: Class Code = 0011, Error Code = 0005, Minor Code = 0026"
        # Class Code = major, Minor Code = minor; middle Error Code field is ignored
        pattern2 = r'Error Logged:\s*Class Code\s*=\s*([0-9A-Fa-f]+),\s*Error Code\s*=\s*([0-9A-Fa-f]+),\s*Minor Code\s*=\s*([0-9A-Fa-f]+)'

        # Pattern 3: IPSD errors "ERROR: C8XXXXXXX:..."
        pattern3 = r'ERROR:\s*(C8[0-9A-Fa-f]{7}):([^\s]+)'

        # Pattern 4: "Enhanced warning of type N logged:" (multi-line block)
        pattern4 = r'Enhanced warning of type (\d+) logged:'

        # Pattern 5: RC Fatal multi-line block starting with **FATAL ERROR** or similar
        # Matches: "**FATAL ERROR**", "FATAL ERROR:", "RC_FATAL_ERROR", "FATAL_ERROR!"
        pattern5_trigger = re.compile(
            r'(?:\*\*FATAL ERROR\*\*|FATAL ERROR:|RC_FATAL_ERROR!?|FATAL_ERROR!)',
            re.IGNORECASE
        )

        # Pattern 6: Standalone combined RC Fatal code (exactly 8 hex digits, outside a FATAL ERROR block)
        # Upper 16 bits = context, bits [15:8] = major, bits [7:0] = minor
        # Require exactly 8 digits to avoid false-positive matches on shorter hex values
        pattern6 = re.compile(r'(?:Error Code|RC Fatal Error Code)\s*=\s*(0x[0-9A-Fa-f]{8})\b', re.IGNORECASE)

        # Pattern 7a (MMC on-die uC): major/minor on the same line — MUST be checked before
        # pattern5 because "Fatal Error:" also matches the FATAL ERROR: trigger.
        # "Fatal Error: MMC registered Major Code = 0xF2, Minor Code = 0x19"
        pattern7a = re.compile(
            r'Fatal Error:\s+MMC registered\s+Major Code\s*=\s*(0x[0-9A-Fa-f]+)'
            r'[,\s]+Minor Code\s*=\s*(0x[0-9A-Fa-f]+)',
            re.IGNORECASE
        )

        # Pattern 7b (FSP host side): reports the same MajorCode/MinorCode relayed from MMC.
        # "MMC Application returned Error 0x... MajorCode = 0x... MinorCode = 0x..."
        # "MMC Application Fatal Error, MajorCode 0xf2, MinorCode 0x19"
        # "Unexpected Kernel error category Error 0x... MajorCode = 0x... MinorCode = 0x..."
        pattern7b = re.compile(
            r'(?:MMC Application.*?Error|Unexpected Kernel error category Error)'
            r'.*?(?:MajorCode\s*[=\s]\s*|Major\s*Code\s*=\s*)(0x[0-9A-Fa-f]+)'
            r'[,.\s]+(?:MinorCode\s*[=\s]\s*|Minor\s*Code\s*=\s*)(0x[0-9A-Fa-f]+)',
            re.IGNORECASE
        )

        # Pattern 7c (MMC status-only): kernel/polling errors without MajorCode/MinorCode.
        # "N0.M0: Error Receiving work, Status = 0x4"
        # "MMC Kernel returned Error Code = 0x..."  /  "MMC Kernel returned FW Exception Error Code = 0x..."
        # "ERROR: <tag>: MMC Fatal Error - MMC Status = 0x..."
        # "ERROR: <tag>: MMC Double Exception Error - MMC Status = 0x..."
        pattern7c = re.compile(
            r'(?:'
            # Polling loop error: "N0.M0: Error Receiving work, Status = 0x4"
            r'N\d+\.M\d+:.*?Error Receiving work.*?Status\s*=\s*(0x[0-9A-Fa-f]+)'
            # Data transfer errors: "N0.M0: Error sending/getting X to/from the MMC, Status = 0x..."
            r'|N\d+\.M\d+:.*?Error (?:sending|getting)\b.*?(?:to|from) the MMC.*?Status\s*=\s*(0x[0-9A-Fa-f]+)'
            # Command execution error: "N0.M0: Attempting to execute Command 0xNN on the MMC returned Status = 0x..."
            r'|N\d+\.M\d+:.*?execute Command.*?MMC returned Status\s*=\s*(0x[0-9A-Fa-f]+)'
            # FSP kernel error codes (no N.M prefix, from closed-source FSP)
            r'|MMC Kernel returned(?:\s+FW Exception)?\s+Error Code\s*=\s*(0x[0-9A-Fa-f]+)'
            # FSP low-level status: "ERROR: <tag>: MMC Fatal/Double Exception Error - MMC Status = 0x..."
            r'|MMC (?:Fatal|Double Exception) Error\s*-\s*MMC Status\s*=\s*(0x[0-9A-Fa-f]+)'
            r')',
            re.IGNORECASE
        )

        lines = log_text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # Strip optional timestamp prefix like "[2026-02-05-18:24:53] "
            clean = re.sub(r'^\[[\d\-:]+\]\s*', '', line).strip()

            # Pattern 4 (Enhanced warning blocks) — highest EWL priority
            match = re.search(pattern4, clean)
            if match:
                ewl_type = match.group(1)
                block_data, lines_consumed = self._parse_enhanced_warning_block(lines, i, ewl_type)
                if block_data:
                    codes.append(block_data)
                i += lines_consumed
                continue

            # Pattern 7a (MUST be before Pattern 5): MMC on-die uC fatal error.
            # "Fatal Error: MMC registered Major Code = 0xF2, Minor Code = 0x19"
            # This line also matches the FATAL ERROR: trigger in Pattern 5, so intercept it first.
            mmc_match = pattern7a.search(clean)
            if mmc_match:
                major = f"0x{int(mmc_match.group(1), 16):02X}"
                minor = f"0x{int(mmc_match.group(2), 16):02X}"
                context_lines = [clean]
                j = i + 1
                # Consume up to 5 following lines as context (the FSP relay + polling lines).
                # Stop at blank lines or a new FATAL ERROR block to avoid cross-block contamination.
                while j < min(i + 6, len(lines)):
                    next_clean = re.sub(r'^\[[\d\-:]+\]\s*', '', lines[j]).strip()
                    if not next_clean or pattern5_trigger.search(next_clean):
                        break
                    context_lines.append(next_clean)
                    j += 1
                codes.append({
                    'type': 'RC_FATAL',
                    'major': major,
                    'minor': minor,
                    'socket': None,
                    'mmc_source': 'mmc_firmware',
                    'context': '\n'.join(context_lines)
                })
                i = j
                continue

            # Pattern 7b: FSP host-side relay of MMC MajorCode/MinorCode.
            # "MMC Application returned Error 0x... MajorCode = 0x... MinorCode = 0x..."
            # "MMC Application Fatal Error, MajorCode 0xf2, MinorCode 0x19"
            mmc_match = pattern7b.search(clean)
            if mmc_match:
                major = f"0x{int(mmc_match.group(1), 16):02X}"
                minor = f"0x{int(mmc_match.group(2), 16):02X}"
                context_lines = [lines[j].strip() for j in range(max(0, i-2), min(len(lines), i+3))]
                codes.append({
                    'type': 'RC_FATAL',
                    'major': major,
                    'minor': minor,
                    'socket': None,
                    'mmc_source': 'fsp_host',
                    'context': '\n'.join(context_lines)
                })
                i += 1
                continue

            # Pattern 7c: MMC status-only errors (no MajorCode/MinorCode).
            # Emitted as MMC_STATUS type — not RC_FATAL — because there is no code to decode.
            mmc_match = pattern7c.search(clean)
            if mmc_match:
                # First non-None capture group is the status/error code
                status_code = next((g for g in mmc_match.groups() if g is not None), 'UNKNOWN')
                context_lines = [lines[j].strip() for j in range(max(0, i-2), min(len(lines), i+3))]
                codes.append({
                    'type': 'MMC_STATUS',
                    'status_code': status_code,
                    'raw_line': clean,
                    'context': '\n'.join(context_lines)
                })
                i += 1
                continue

            # Pattern 5: RC Fatal block trigger line
            if pattern5_trigger.search(clean):
                block_data, lines_consumed = self._parse_rc_fatal_block(lines, i)
                if block_data:
                    codes.append(block_data)
                i += lines_consumed
                continue

            # Pattern 1: inline EWL codes
            match = re.search(pattern1, clean)
            if match:
                major = "0x" + match.group(1)[2:].upper()
                minor = "0x" + match.group(2)[2:].upper()
                socket_match = re.match(r'S(\d+),', clean)
                socket = socket_match.group(1) if socket_match else None
                codes.append({
                    'type': 'EWL',
                    'major': major,
                    'minor': minor,
                    'socket': socket,
                    'context': line.strip()
                })
                i += 1
                continue

            # Pattern 2: legacy "Error Logged" format
            match = re.search(pattern2, clean)
            if match:
                class_code = match.group(1)
                minor_code = match.group(3)
                major = f"0x{int(class_code, 16):02X}"
                minor = f"0x{int(minor_code, 16):02X}"
                socket_match = re.match(r'S(\d+),', clean)
                socket = socket_match.group(1) if socket_match else None
                context_lines = [lines[j].strip() for j in range(max(0, i-2), min(len(lines), i+3))]
                codes.append({
                    'type': 'EWL',
                    'major': major,
                    'minor': minor,
                    'socket': socket,
                    'context': '\n'.join(context_lines)
                })
                i += 1
                continue

            # Pattern 3: IPSD
            match = re.search(pattern3, clean)
            if match:
                ipsd_code = match.group(1)
                guid = match.group(2)
                context_lines = [lines[j].strip() for j in range(max(0, i-2), min(len(lines), i+3))]
                codes.append({
                    'type': 'IPSD',
                    'ipsd_code': ipsd_code,
                    'guid': guid,
                    'socket': None,
                    'context': '\n'.join(context_lines)
                })
                i += 1
                continue

            # Pattern 6: standalone combined RC Fatal code (outside a FATAL ERROR block)
            match = pattern6.search(clean)
            if match:
                combined = match.group(1)
                decoded = self.decode_error_code(combined)
                if decoded['decoded'].get('major_name'):
                    context_lines = [lines[j].strip() for j in range(max(0, i-2), min(len(lines), i+3))]
                    codes.append({
                        'type': 'RC_FATAL',
                        'major': decoded['major_code'],
                        'minor': decoded['minor_code'],
                        'combined_code': decoded['error_code'],
                        'socket': None,
                        'context': '\n'.join(context_lines)
                    })
                i += 1
                continue

            i += 1

        # Also scan all lines for MCHECK error codes (pass full lines list once)
        codes.extend(self._parse_mcheck(lines))

        # Classify known-expected/informational messages so they are not left unaccounted for
        codes.extend(self._parse_known_benign(lines))

        return codes

    def _parse_known_benign(self, lines):
        """
        Scan all log lines for known-expected or informational messages that
        commonly appear to be errors but are benign given the platform context.

        Returns a list of dicts with type='BENIGN'.
        Each dict: label, explanation, raw_line.
        """
        found = []
        for line in lines:
            clean = re.sub(r'^\[[\d\-:]+\]\s*', '', line).strip().rstrip('\r')
            for pattern, label, explanation in self._KNOWN_BENIGN_PATTERNS:
                if pattern.search(clean):
                    found.append({
                        'type': 'BENIGN',
                        'label': label,
                        'explanation': explanation,
                        'raw_line': clean,
                    })
                    break  # Only first matching pattern per line
        return found

    def _parse_mcheck(self, lines):
        """
        Scan log lines for MCHECK error code patterns and return found entries.

        Detects three formats emitted by Intel firmware:
          1. "MCheck Error code post second patch load is: 0x250E"
             (CpuInitPostMem.c, primary format)
          2. "[<tag>] <func> TeeErrorCode = 0x250e"
             (IfsCallbackPostMcheck.c)
          3. "MCheck Error 0x250E" / "MCHECK error 0x250e"
             (fallback for other BIOS prints and HSDES descriptions)

        Returns list of dicts with type='MCHECK'.
        """
        _p1 = re.compile(r'MCheck Error code.*?is:\s*(0x[0-9A-Fa-f]+)', re.IGNORECASE)
        _p2 = re.compile(r'\bTeeErrorCode\s*=\s*(0x[0-9A-Fa-f]+)')
        _p3 = re.compile(r'mcheck\s+error\b.*?(0x[0-9A-Fa-f]+)', re.IGNORECASE)

        found = []
        for i, line in enumerate(lines):
            clean = re.sub(r'^\[[\d\-:]+\]\s*', '', line).strip()

            for pattern in (_p1, _p2, _p3):
                m = pattern.search(clean)
                if m:
                    code = m.group(1)
                    try:
                        if int(code, 16) == 0:
                            break
                    except ValueError:
                        break
                    context_lines = [
                        lines[j].strip()
                        for j in range(max(0, i - 1), min(len(lines), i + 3))
                    ]
                    found.append({
                        'type': 'MCHECK',
                        'code': code,
                        'context': '\n'.join(context_lines),
                    })
                    break  # Only one match per line

        return found

    def _parse_rc_fatal_block(self, lines, start_idx):
        """
        Parse a multi-line RC Fatal block starting at the trigger line.

        Recognises formats emitted by Intel BIOS firmware:
          **FATAL ERROR**
          Major Error Code = 0xCD
          Minor Error Code = 0x2C
          Socket = 0

        Also handles single-line forms like:
          RC_FATAL_ERROR! path/file.c: 741   (file-reference only)

        Returns (dict | None, lines_consumed).
        """
        trigger_line = re.sub(r'^\[[\d\-:]+\]\s*', '', lines[start_idx]).strip()

        data = {
            'type': 'RC_FATAL',
            'major': None,
            'minor': None,
            'combined_code': None,
            'socket': None,
            'file_ref': None,
            'context_lines': [trigger_line]
        }

        # Compile pattern5 trigger once for use as stop-condition inside lookahead
        _p5 = re.compile(
            r'(?:\*\*FATAL ERROR\*\*|FATAL ERROR:|RC_FATAL_ERROR!?|FATAL_ERROR!)',
            re.IGNORECASE
        )
        # Exact-8-digit combined code pattern (bits[15:8]=major, bits[7:0]=minor)
        _combined = re.compile(
            r'(?:Error Code|RC Fatal Error Code)\s*=\s*(0x[0-9A-Fa-f]{8})\b',
            re.IGNORECASE
        )

        # Extract file reference from trigger line itself (RC_FATAL_ERROR! file.c: 741)
        file_ref_match = re.search(r'(?:RC_FATAL_ERROR!?|FATAL_ERROR!)\s+(.*?:\s*\d+)', trigger_line, re.IGNORECASE)
        if file_ref_match:
            data['file_ref'] = file_ref_match.group(1).strip()

        # Bug fix #2: also scan the trigger line itself for a combined code
        # (handles single-line form: "RC_FATAL_ERROR! RC Fatal Error Code = 0x3000CD2C")
        m = _combined.search(trigger_line)
        if m:
            decoded = self.decode_error_code(m.group(1))
            data['combined_code'] = decoded['error_code']
            data['major'] = decoded['major_code']
            data['minor'] = decoded['minor_code']

        # Scan up to 20 following lines for code fields
        i = start_idx + 1
        block_end = min(start_idx + 20, len(lines))

        while i < block_end:
            raw = lines[i]
            clean = re.sub(r'^\[[\d\-:]+\]\s*', '', raw).strip()

            # Stop at blank line, next FATAL ERROR block, or other recognised log section
            # Bug fix #1: stop at another FATAL ERROR trigger so adjacent blocks are not merged
            if not clean:
                break
            if _p5.search(clean) or re.search(r'Enhanced warning of type|ERROR:\s*C8', clean):
                break

            data['context_lines'].append(clean)

            # Major Error Code = 0xXX
            m = re.search(r'Major\s+(?:Error|Warning)\s+Code\s*=\s*(0x[0-9A-Fa-f]+)', clean, re.IGNORECASE)
            if m:
                data['major'] = "0x" + m.group(1)[2:].upper()

            # Minor Error Code = 0xXX
            m = re.search(r'Minor\s+(?:Error|Warning)\s+Code\s*=\s*(0x[0-9A-Fa-f]+)', clean, re.IGNORECASE)
            if m:
                data['minor'] = "0x" + m.group(1)[2:].upper()

            # Combined code (exactly 8 hex digits to avoid false positives)
            m = _combined.search(clean)
            if m:
                decoded = self.decode_error_code(m.group(1))
                data['combined_code'] = decoded['error_code']
                if not data['major']:
                    data['major'] = decoded['major_code']
                if not data['minor']:
                    data['minor'] = decoded['minor_code']

            # Socket
            m = re.search(r'^Socket\s*=?\s*(\d+)', clean, re.IGNORECASE)
            if m:
                data['socket'] = m.group(1)

            i += 1

        lines_consumed = i - start_idx
        data['context'] = '\n'.join(data['context_lines'][:15])

        # Accept the block if we have at least a major code OR a file reference
        if data['major'] or data['file_ref']:
            return data, lines_consumed

        return None, lines_consumed
    
    def _parse_enhanced_warning_block(self, lines, start_idx, ewl_type):
        """
        Parse multi-line Enhanced warning block starting from the marker line.
        
        Format example:
            Enhanced warning of type 1 logged:
            Major Warning Code = 0x0A, Minor Warning Code = 0x10,
            Major Checkpoint: 0xB7
            Minor Checkpoint: 0x51
            Socket 0
            Channel 15
            Dimm 0
            Rank 1
        
        Returns tuple: (dict with parsed data or None if invalid, lines_consumed)
        """
        data = {
            'type': 'EWL',
            'ewl_type': ewl_type,
            'major': None,
            'minor': None,
            'socket': None,
            'channel': None,
            'dimm': None,
            'rank': None,
            'major_checkpoint': None,
            'minor_checkpoint': None,
            'context_lines': []
        }
        
        # Capture the marker line
        marker_line = lines[start_idx].strip()
        data['context_lines'].append(marker_line)
        
        # Parse next 15 lines max (Enhanced warning blocks are typically 5-15 lines)
        i = start_idx + 1
        block_end = min(start_idx + 20, len(lines))
        
        while i < block_end:
            line = lines[i]
            
            # Strip timestamp prefix like "[2026-02-05-18:24:53] "
            clean_line = re.sub(r'^\[[\d\-:]+\]\s*', '', line).strip()
            
            # Stop at empty line or next "Enhanced warning" marker or next timestamp section
            if not clean_line or 'Enhanced warning of type' in clean_line:
                break
            
            # Stop at MMC handler markers (indicates end of block)
            if 'MMC[' in clean_line and 'MmcHostAppDataQueueHandler' in clean_line:
                break
            
            # Stop if we hit another log entry (starts with Node prefix or other markers)
            if clean_line and not clean_line.startswith('>>>'):
                # Check if it's a different log entry (not a field we're parsing)
                if re.match(r'^N\d+\.(M\d+\.)?C\d+\.D\d+:', clean_line):
                    # This is a context line, not a field - we can include it but should stop soon
                    data['context_lines'].append(line.strip())
                    i += 1
                    break
            
            # Skip lines with ">>>>>>>" prefix (MMC output format - strip it)
            clean_line = clean_line.lstrip('> ')
            
            # Parse Major/Minor Warning Code (can be on same line or separate)
            major_match = re.search(r'Major Warning Code\s*=\s*(0x[0-9A-Fa-f]+)', clean_line)
            if major_match:
                data['major'] = "0x" + major_match.group(1)[2:].upper()

            minor_match = re.search(r'Minor Warning Code\s*=\s*(0x[0-9A-Fa-f]+)', clean_line)
            if minor_match:
                data['minor'] = "0x" + minor_match.group(1)[2:].upper()

            # Parse checkpoints
            if 'Major Checkpoint:' in clean_line:
                cp_match = re.search(r'Major Checkpoint:\s*(0x[0-9A-Fa-f]+)', clean_line)
                if cp_match:
                    data['major_checkpoint'] = "0x" + cp_match.group(1)[2:].upper()

            if 'Minor Checkpoint:' in clean_line:
                cp_match = re.search(r'Minor Checkpoint:\s*(0x[0-9A-Fa-f]+)', clean_line)
                if cp_match:
                    data['minor_checkpoint'] = "0x" + cp_match.group(1)[2:].upper()
            
            # Parse topology fields - must match line start (after cleaning)
            if re.match(r'^Socket\s+\d+', clean_line):
                socket_match = re.search(r'Socket\s+(\d+)', clean_line)
                if socket_match:
                    data['socket'] = socket_match.group(1)
            
            if re.match(r'^Channel\s+\d+', clean_line):
                channel_match = re.search(r'Channel\s+(\d+)', clean_line)
                if channel_match:
                    data['channel'] = channel_match.group(1)
            
            if re.match(r'^Dimm\s+\d+', clean_line):
                dimm_match = re.search(r'Dimm\s+(\d+)', clean_line)
                if dimm_match:
                    data['dimm'] = dimm_match.group(1)
            
            if re.match(r'^Rank\s+\d+', clean_line):
                rank_match = re.search(r'Rank\s+(\d+)', clean_line)
                if rank_match:
                    data['rank'] = rank_match.group(1)
            
            # Parse Type 2 specific fields (Strobe, Level, Group, Eyesize)
            if 'Strobe:' in clean_line:
                strobe_match = re.search(r'Strobe:\s+(\d+)', clean_line)
                if strobe_match:
                    data['strobe'] = strobe_match.group(1)
            
            if 'Level:' in clean_line:
                level_match = re.search(r'Level:\s+(\w+)', clean_line)
                if level_match:
                    data['level'] = level_match.group(1)
            
            if 'Group:' in clean_line:
                group_match = re.search(r'Group:\s+(\w+)', clean_line)
                if group_match:
                    data['group'] = group_match.group(1)
            
            if 'Eyesize' in clean_line:
                eyesize_match = re.search(r'Eyesize\s+(\d+)', clean_line)
                if eyesize_match:
                    data['eyesize'] = eyesize_match.group(1)
            
            data['context_lines'].append(line.strip())
            i += 1
        
        # Calculate lines consumed (including the marker line)
        lines_consumed = i - start_idx
        
        # Build context string
        data['context'] = '\n'.join(data['context_lines'][:15])  # Limit context
        
        # Only return data if we found major/minor codes
        if data['major'] and data['minor']:
            return data, lines_consumed
        
        return None, lines_consumed
    
    def generate_summary(self, codes):
        """
        Generate a summary report from list of codes.
        
        Args:
            codes: List of dicts with major, minor, socket, context, type keys
        
        Returns:
            String containing formatted summary report
        """
        if not codes:
            return "No error codes found in log.\n"

        # Separate by type
        ewl_codes = [c for c in codes if c.get('type') == 'EWL']
        ipsd_codes = [c for c in codes if c.get('type') == 'IPSD']
        rc_fatal_codes = [c for c in codes if c.get('type') == 'RC_FATAL']
        mcheck_codes = [c for c in codes if c.get('type') == 'MCHECK']
        mmc_status_codes = [c for c in codes if c.get('type') == 'MMC_STATUS']
        benign_codes = [c for c in codes if c.get('type') == 'BENIGN']

        error_codes = [c for c in codes if c.get('type') not in ('BENIGN',)]

        summary = []
        summary.append("## BIOS Error Code Analysis\n\n")
        summary.append(f"**Total error codes found:** {len(error_codes)}\n")
        summary.append(f"- EWL errors: {len(ewl_codes)}\n")
        summary.append(f"- IPSD errors: {len(ipsd_codes)}\n")
        summary.append(f"- RC Fatal errors: {len(rc_fatal_codes)}\n")
        summary.append(f"- MCHECK errors: {len(mcheck_codes)}\n")
        if mmc_status_codes:
            summary.append(f"- MMC status events: {len(mmc_status_codes)}\n")
        if benign_codes:
            # Count by unique label for summary
            benign_labels = len({c['label'] for c in benign_codes})
            summary.append(f"- Known expected/informational messages: {len(benign_codes)} "
                           f"occurrences ({benign_labels} distinct type(s)) — see end of report\n")
        summary.append("\n")
        
        # Process EWL codes
        if ewl_codes:
            summary.append("## EWL (Enhanced Warning Log) Errors\n\n")
            
            # Group by (major, minor) and collect sockets/contexts
            code_groups = defaultdict(lambda: {
                'count': 0, 
                'sockets': set(), 
                'topology': [],  # List of (socket, channel, dimm, rank) tuples
                'contexts': [],
                'checkpoints': set()
            })
            for entry in ewl_codes:
                key = (entry['major'], entry['minor'])
                code_groups[key]['count'] += 1
                if entry.get('socket'):
                    code_groups[key]['sockets'].add(entry['socket'])
                
                # Collect topology information
                if entry.get('channel') is not None:
                    topo = (
                        entry.get('socket', '-'),
                        entry.get('channel', '-'),
                        entry.get('dimm', '-'),
                        entry.get('rank', '-')
                    )
                    code_groups[key]['topology'].append(topo)
                
                # Collect checkpoint information
                if entry.get('major_checkpoint'):
                    cp_pair = f"{entry['major_checkpoint']}/{entry['minor_checkpoint']}"
                    code_groups[key]['checkpoints'].add(cp_pair)
                
                code_groups[key]['contexts'].append(entry.get('context', ''))
            
            # Sort by count (descending)
            sorted_codes = sorted(code_groups.items(), key=lambda x: x[1]['count'], reverse=True)
            
            for idx, ((major, minor), data) in enumerate(sorted_codes, 1):
                info = self.decode_code(major, minor)
                count = data['count']
                sockets = sorted(data['sockets'])
                
                # Code header with count
                summary.append(f"### Error #{idx}: `{major} / {minor}`\n\n")
                summary.append(f"**Occurrences:** {count}\n\n")
                
                # Socket information
                if sockets:
                    socket_str = ', '.join([f"S{s}" for s in sockets])
                    summary.append(f"**Sockets:** {socket_str}\n\n")
                
                # Topology information (Channel/Dimm/Rank)
                if data['topology']:
                    summary.append(f"**Affected Hardware:**\n")
                    # Show unique topology combinations (limit to 10)
                    unique_topo = list(set(data['topology']))
                    for topo in unique_topo[:10]:
                        s, c, d, r = topo
                        topo_str = f"Socket {s}, Channel {c}, DIMM {d}, Rank {r}"
                        summary.append(f"- {topo_str}\n")
                    if len(unique_topo) > 10:
                        summary.append(f"- ... and {len(unique_topo) - 10} more locations\n")
                    summary.append("\n")
                
                # Checkpoint information
                if data['checkpoints']:
                    cp_list = sorted(data['checkpoints'])
                    summary.append(f"**Checkpoints:** {', '.join(cp_list)}\n\n")
                
                # Major name
                if info['major_name']:
                    summary.append(f"**Major Code:** {info['major_name']}\n\n")
                
                # Minor name
                if info['minor_name']:
                    summary.append(f"**Minor Code:** {info['minor_name']}\n\n")
                
                # Description
                if info['major_desc'] or info['minor_desc']:
                    summary.append(f"**Description:**\n")
                    if info['major_desc']:
                        summary.append(f"- {info['major_desc']}\n")
                    if info['minor_desc']:
                        summary.append(f"- {info['minor_desc']}\n")
                    summary.append("\n")
                
                # Not found message
                if not info['major_name']:
                    summary.append("*Code not found in database*\n\n")
                
                # Show first context example
                if data['contexts'] and data['contexts'][0]:
                    summary.append(f"**Example Context:**\n```\n{data['contexts'][0][:500]}\n```\n\n")
                
                summary.append("---\n\n")

        # Process IPSD codes
        if ipsd_codes:
            summary.append("## IPSD (Intel Platform Service Provider) Errors\n\n")

            # Group by IPSD code
            ipsd_groups = defaultdict(lambda: {'count': 0, 'guids': set(), 'contexts': []})
            for entry in ipsd_codes:
                key = entry['ipsd_code']
                ipsd_groups[key]['count'] += 1
                if entry.get('guid'):
                    ipsd_groups[key]['guids'].add(entry['guid'])
                ipsd_groups[key]['contexts'].append(entry.get('context', ''))

            sorted_ipsd = sorted(ipsd_groups.items(), key=lambda x: x[1]['count'], reverse=True)

            for idx, (ipsd_code, data) in enumerate(sorted_ipsd, 1):
                decoded = self.decode_ipsd_error(ipsd_code)
                count = data['count']
                guids = list(data['guids'])

                summary.append(f"### IPSD Error #{idx}: `{ipsd_code}`\n\n")
                summary.append(f"**Occurrences:** {count}\n\n")
                summary.append(f"**Error Code:** {decoded['code']}\n\n")
                summary.append(f"**Description:** {decoded['description']}\n\n")

                if guids:
                    summary.append("**Associated GUIDs:**\n")
                    for guid in guids[:3]:
                        summary.append(f"- `{guid}`\n")
                    if len(guids) > 3:
                        summary.append(f"- ... and {len(guids) - 3} more\n")
                    summary.append("\n")

                if data['contexts'] and data['contexts'][0]:
                    summary.append(f"**Example Context:**\n```\n{data['contexts'][0][:500]}\n```\n\n")

                summary.append("---\n\n")

        # Process RC Fatal errors
        if rc_fatal_codes:
            summary.append("## RC Fatal Errors\n\n")

            rc_groups = defaultdict(lambda: {
                'count': 0, 'sockets': set(), 'file_refs': set(), 'contexts': [],
                'origins': set()
            })
            for entry in rc_fatal_codes:
                key = (entry.get('major') or 'UNKNOWN', entry.get('minor') or 'UNKNOWN')
                rc_groups[key]['count'] += 1
                if entry.get('socket'):
                    rc_groups[key]['sockets'].add(entry['socket'])
                if entry.get('file_ref'):
                    rc_groups[key]['file_refs'].add(entry['file_ref'])
                rc_groups[key]['contexts'].append(entry.get('context', ''))
                if entry.get('mmc_source'):
                    rc_groups[key]['origins'].add(entry['mmc_source'])

            sorted_rc = sorted(rc_groups.items(), key=lambda x: x[1]['count'], reverse=True)

            for idx, ((major, minor), data) in enumerate(sorted_rc, 1):
                count = data['count']
                sockets = sorted(data['sockets'])

                summary.append(f"### RC Fatal Error #{idx}: `{major} / {minor}`\n\n")
                summary.append(f"**Occurrences:** {count}\n\n")

                if sockets:
                    summary.append(f"**Sockets:** {', '.join(['S' + s for s in sockets])}\n\n")

                # Show MMC origin when detected
                _origin_labels = {
                    'mmc_firmware': 'MMC on-die uC firmware',
                    'fsp_host': 'FSP host firmware (MMC relay)',
                }
                if data['origins']:
                    labels = [_origin_labels.get(o, o) for o in sorted(data['origins'])]
                    summary.append(f"**Origin:** {', '.join(labels)}\n\n")

                # Decode via RC Fatal database; enable generic minor fallback for any MMC origin
                # (covers FSP-host-only logs where Pattern 7a line is absent)
                mmc_origin = bool(data['origins'])
                if major != 'UNKNOWN':
                    info = self.decode_rc_fatal_error(
                        major, minor if minor != 'UNKNOWN' else None, mmc_origin=mmc_origin
                    )
                    if info['major_name']:
                        summary.append(f"**Major Code:** {info['major_name']}\n\n")
                    if info['minor_name']:
                        summary.append(f"**Minor Code:** {info['minor_name']}\n\n")
                    if info['major_desc'] or info['minor_desc']:
                        summary.append("**Description:**\n")
                        if info['major_desc']:
                            summary.append(f"- {info['major_desc']}\n")
                        if info['minor_desc']:
                            summary.append(f"- {info['minor_desc']}\n")
                        summary.append("\n")
                    if info.get('major_source'):
                        summary.append(f"**Source:** `{info['major_source']}`\n\n")
                    if not info['major_name']:
                        summary.append("*Code not found in RC Fatal database*\n\n")

                if data['file_refs']:
                    summary.append("**File References:**\n")
                    for ref in sorted(data['file_refs'])[:3]:
                        summary.append(f"- `{ref}`\n")
                    summary.append("\n")

                if data['contexts'] and data['contexts'][0]:
                    summary.append(f"**Example Context:**\n```\n{data['contexts'][0][:500]}\n```\n\n")

                summary.append("---\n\n")

        # Process MCHECK errors
        if mcheck_codes:
            summary.append("## MCHECK (Platform Configuration Check) Errors\n\n")

            mcheck_groups = defaultdict(lambda: {'count': 0, 'contexts': []})
            for entry in mcheck_codes:
                key = entry['code'].lower()
                mcheck_groups[key]['count'] += 1
                mcheck_groups[key]['contexts'].append(entry.get('context', ''))

            sorted_mcheck = sorted(
                mcheck_groups.items(), key=lambda x: x[1]['count'], reverse=True
            )

            for idx, (code, data) in enumerate(sorted_mcheck, 1):
                info = self.mcheck_decoder.decode(code)
                count = data['count']

                summary.append(f"### MCHECK Error #{idx}: `{code}`\n\n")
                summary.append(f"**Occurrences:** {count}\n\n")

                if info['name']:
                    summary.append(f"**Name:** {info['name']}\n\n")
                if info['description']:
                    summary.append(f"**Description:** {info['description']}\n\n")
                if info['dfx_group_name']:
                    summary.append(
                        f"**DFX Group:** {info['dfx_group_name']} ({info['dfx_group_id']})\n\n"
                    )
                if info['dfx_bit_name']:
                    summary.append(
                        f"**DFX Bit:** {info['dfx_bit_name']} ({info['dfx_bit_id']})\n\n"
                    )
                if not info['found']:
                    summary.append("*Code not found in MCHECK database*\n\n")

                if data['contexts'] and data['contexts'][0]:
                    summary.append(
                        f"**Example Context:**\n```\n{data['contexts'][0][:500]}\n```\n\n"
                    )

                summary.append("---\n\n")

        # Process MMC status events (kernel/polling errors without MajorCode/MinorCode)
        if mmc_status_codes:
            summary.append("## MMC Status Events\n\n")
            summary.append(
                "These lines indicate MMC (Memory Module Controller) host-side errors "
                "or polling failures. They typically accompany an RC Fatal Error above "
                "and identify which MMC instance was affected.\n\n"
            )

            mmc_status_groups = defaultdict(lambda: {'count': 0, 'raw_lines': set(), 'contexts': []})
            for entry in mmc_status_codes:
                key = entry.get('status_code', 'UNKNOWN')
                mmc_status_groups[key]['count'] += 1
                mmc_status_groups[key]['raw_lines'].add(entry.get('raw_line', ''))
                mmc_status_groups[key]['contexts'].append(entry.get('context', ''))

            sorted_mmc = sorted(mmc_status_groups.items(), key=lambda x: x[1]['count'], reverse=True)

            for idx, (status_code, data) in enumerate(sorted_mmc, 1):
                summary.append(f"### MMC Status #{idx}: `{status_code}`\n\n")
                summary.append(f"**Occurrences:** {data['count']}\n\n")
                if data['raw_lines']:
                    first_raw = next(iter(data['raw_lines']))
                    summary.append(f"**Log line:** `{first_raw}`\n\n")
                if data['contexts'] and data['contexts'][0]:
                    summary.append(f"**Example Context:**\n```\n{data['contexts'][0][:500]}\n```\n\n")
                summary.append("---\n\n")

        # Process known expected / informational messages
        if benign_codes:
            summary.append("## Known Expected / Informational Messages\n\n")
            summary.append(
                "The following messages were detected but are classified as **expected behavior** "
                "based on OKS BIOS source analysis and platform configuration. "
                "They do not indicate bugs and can be safely ignored.\n\n"
            )

            # Group by label (preserving insertion order for consistent output)
            benign_groups: dict = {}
            for entry in benign_codes:
                label = entry['label']
                if label not in benign_groups:
                    benign_groups[label] = {
                        'count': 0,
                        'explanation': entry['explanation'],
                        'examples': [],
                    }
                benign_groups[label]['count'] += 1
                if len(benign_groups[label]['examples']) < 2:
                    benign_groups[label]['examples'].append(entry['raw_line'])

            for label, data in benign_groups.items():
                summary.append(f"### ✓ `{label}` — {data['count']} occurrence(s)\n\n")
                summary.append(f"**Why expected:** {data['explanation']}\n\n")
                if data['examples']:
                    summary.append(f"**Example:** `{data['examples'][0][:200]}`\n\n")
                summary.append("---\n\n")

        return ''.join(summary)

    def format_single_code(self, result):
        """Format single code decode result for display."""
        output = []
        output.append(f"Code: {result['major_code']}")
        if result['minor_code']:
            output.append(f" / {result['minor_code']}")
        output.append("\n")

        if result['major_name']:
            output.append(f"Name: {result['major_name']}")
            if result['minor_name']:
                output.append(f" / {result['minor_name']}")
            output.append("\n")

        if result['major_desc']:
            output.append(f"Description: {result['major_desc']}")
            if result['minor_desc']:
                output.append(f" / {result['minor_desc']}")
            output.append("\n")

        if not result['major_name']:
            output.append("Code not found in database\n")

        return ''.join(output)


def _sanitize_for_json(codes):
    """Convert parsed code entries to JSON-serialisable dicts.

    Removes internal-only fields (context_lines) and converts any set-typed
    fields (sockets, checkpoints) to sorted lists.
    """
    safe = []
    for c in codes:
        d = dict(c)
        d.pop('context_lines', None)
        for key in ('sockets', 'checkpoints'):
            if isinstance(d.get(key), set):
                d[key] = sorted(d[key])
        safe.append(d)
    return safe


def main():
    """Main entry point for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(description='Decode BIOS EWL / IPSD / RC Fatal error codes')
    parser.add_argument('--code', help='Major code to decode (e.g., 0x29)')
    parser.add_argument('--minor', help='Minor code to decode (e.g., 0x15)')
    parser.add_argument('--log', help='Log file to analyze')
    parser.add_argument('--db', default=None, help='Path to EWL database (default: ewl_codes_database.json in script dir)')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Emit machine-readable JSON instead of markdown')

    args = parser.parse_args()

    decoder = EWLDecoder(db_path=args.db)

    # Single code decode
    if args.code:
        major = args.code
        if not major.lower().startswith('0x'):
            major = f"0x{int(major, 0):X}"

        minor = None
        if args.minor:
            minor = args.minor
            if not minor.lower().startswith('0x'):
                minor = f"0x{int(minor, 0):X}"

        result = decoder.decode_code(major, minor)
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(decoder.format_single_code(result))

    # Log analysis — file or stdin
    else:
        if args.log:
            with open(args.log, 'r', errors='replace') as f:
                log_text = f.read()
        elif not sys.stdin.isatty():
            log_text = sys.stdin.read()
        else:
            parser.print_help()
            sys.exit(1)

        codes = decoder.parse_log(log_text)
        if args.json_output:
            print(json.dumps(_sanitize_for_json(codes), indent=2))
        else:
            print(decoder.generate_summary(codes))


if __name__ == '__main__':
    main()
