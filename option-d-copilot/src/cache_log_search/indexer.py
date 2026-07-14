import re
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from collections import Counter


@dataclass
class SectionMetadata:
    """Lightweight section metadata for fast indexing."""
    section_id: int
    section_name: str  # Extracted from header (e.g., file path or identifier)
    timestamp: Optional[str]
    line_range: List[int]  # [start_line, end_line]
    size_bytes: int
    
    def to_dict(self) -> Dict:
        return asdict(self)


class LogChunker:
    """
    Scalable log chunking with lightweight indexing and parallel processing.
    Index stores minimal metadata; detailed analysis runs on-demand via ThreadPool.
    """
    
    def __init__(self, file_path: str, header_pattern: str):
        """
        Initialize the log chunker.
        
        Args:
            file_path: Path to the log file
            header_pattern: Regex pattern to match section headers
        """
        self.file_path = Path(file_path)
        self.pattern = re.compile(header_pattern, re.MULTILINE)
        self.sections: List[SectionMetadata] = []
        self._content_cache: Optional[str] = None
        
    def create_index(self) -> List[SectionMetadata]:
        """
        Create a lightweight JSON index with minimal metadata.
        No previews or full headers - just essential attributes.
        
        Returns:
            List of SectionMetadata objects
        """
        start_time = time.time()
        print(f"Indexing {self.file_path}...")
        
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Find all header matches
        matches = list(self.pattern.finditer(content))
        
        if not matches:
            print("⚠️  No sections found. Check your header pattern.")
            return []
        
        print(f"Found {len(matches)} sections")
        
        sections = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            
            header_text = match.group().strip()
            
            # Calculate line numbers
            line_start = content[:start].count('\n') + 1
            line_end = content[:end].count('\n') + 1
            
            # Extract minimal attributes
            timestamp = self._extract_timestamp(header_text)
            section_name = self._extract_section_name(header_text)
            
            # Create lightweight metadata
            section = SectionMetadata(
                section_id=i + 1,
                section_name=section_name,
                timestamp=timestamp,
                line_range=[line_start, line_end],
                size_bytes=end - start
            )
            
            sections.append(section)
            
        self.sections = sections
        elapsed = time.time() - start_time
        print(f"⏱️  Indexing completed in {elapsed:.2f} seconds")
        return sections
    
    def save_unified_json(
        self, 
        analysis_results: Optional[Dict[int, Dict]] = None,
        output_path: str = "log_analysis.json",
        is_multi_analyzer: bool = False,
        demo_format: bool = False
    ) -> str:
        """
        Save a single unified JSON with index + analysis results.
        
        Args:
            analysis_results: Analysis results from process_sections_parallel() or process_sections_multi_analyzer()
            output_path: Path for the unified JSON file
            is_multi_analyzer: True if results are from multi-analyzer mode
            demo_format: True to use the compact demo.json format (id, name, ts, lines)
            
        Returns:
            Path to the saved file
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        # Build unified structure
        sections_data = []
        for section in self.sections:
            if demo_format:
                # Compact format: id, name, ts, lines, errors, warnings, exceptions, failures
                section_dict = {
                    'id': section.section_id,
                    'name': section.section_name,
                    'ts': section.timestamp or "",
                    'lines': f"{section.line_range[0]}-{section.line_range[1]}"
                }
                
                # Merge analysis results if available
                if analysis_results and section.section_id in analysis_results:
                    result = analysis_results[section.section_id]
                    
                    if is_multi_analyzer:
                        # Extract the demo_format analyzer results if present
                        if 'analyzers' in result and 'demo_format' in result['analyzers']:
                            analyzer_result = result['analyzers']['demo_format'].get('result', {})
                            section_dict.update(analyzer_result)
                    else:
                        # Direct format - merge errors, warnings, exceptions, failures
                        section_dict.update(result)
                else:
                    # No analysis results, add empty structures
                    for key in ['errors', 'warnings', 'exceptions', 'failures']:
                        section_dict[key] = {'uniques': 0, 'anchors': []}
            else:
                # Original verbose format
                section_dict = section.to_dict()
                
                # Merge analysis results if available
                if analysis_results and section.section_id in analysis_results:
                    result = analysis_results[section.section_id]
                    
                    if is_multi_analyzer:
                        # Multi-analyzer format: keep the full structure with timing
                        section_dict['analysis'] = result.get('analyzers', {})
                    else:
                        # Single analyzer format: remove redundant fields
                        analysis_clean = {k: v for k, v in result.items() 
                                        if k not in ['section_id', 'section_name', 'timestamp']}
                        section_dict['analysis'] = analysis_clean
                else:
                    section_dict['analysis'] = None
            
            sections_data.append(section_dict)
        
        # Create unified JSON structure
        if demo_format:
            unified_data = {
                "file": str(self.file_path),
                "indexed_at": datetime.now().isoformat(),
                "total_sections": len(self.sections),
                "sections": sections_data
            }
        else:
            unified_data = {
                "source_file": str(self.file_path),
                "indexed_at": datetime.now().isoformat(),
                "total_sections": len(self.sections),
                "analyzed_sections": len(analysis_results) if analysis_results else 0,
                "analysis_mode": "multi-analyzer" if is_multi_analyzer else "single-analyzer",
                "sections": sections_data
            }
        
        output_file = Path(output_path)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(unified_data, f, indent=2)
        
        file_size = output_file.stat().st_size
        print(f"✅ Unified JSON saved: {output_file} ({file_size:,} bytes)")
        return str(output_file)
    
    def extract_section(self, section_id: int) -> Optional[str]:
        """
        Extract the full content of a specific section by ID.
        
        Args:
            section_id: Section number (1-indexed)
            
        Returns:
            Full section content as string
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        if section_id < 1 or section_id > len(self.sections):
            print(f"❌ Invalid section_id: {section_id}. Valid range: 1-{len(self.sections)}")
            return None
        
        section = self.sections[section_id - 1]
        line_start, line_end = section.line_range
        
        # Read specific lines from file
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            content = ''.join(lines[line_start - 1:line_end])
        
        return content
    
    def process_sections_parallel(
        self, 
        analyzer_func: Callable[[int, str, SectionMetadata], Dict[str, Any]],
        max_workers: int = 4,
        section_ids: Optional[List[int]] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        Process sections in parallel using ThreadPoolExecutor (single analyzer).
        Use process_sections_multi_analyzer() for comparing multiple analyzers.
        
        Args:
            analyzer_func: Function(section_id, content, metadata) -> analysis_result
            max_workers: Number of parallel threads
            section_ids: Specific sections to process (None = all sections)
            
        Returns:
            Dictionary mapping section_id to analysis results
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        # Determine which sections to process
        if section_ids is None:
            sections_to_process = self.sections
        else:
            sections_to_process = [s for s in self.sections if s.section_id in section_ids]
        
        results = {}
        total = len(sections_to_process)
        
        start_time = time.time()
        print(f"Processing {total} sections with {max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_section = {}
            for section in sections_to_process:
                content = self.extract_section(section.section_id)
                future = executor.submit(analyzer_func, section.section_id, content, section)
                future_to_section[future] = section.section_id
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_section):
                section_id = future_to_section[future]
                try:
                    result = future.result()
                    results[section_id] = result
                    completed += 1
                    print(f"  ✓ Processed section {section_id} ({completed}/{total})")
                except Exception as e:
                    print(f"  ✗ Error processing section {section_id}: {e}")
                    results[section_id] = {"error": str(e)}
        
        elapsed = time.time() - start_time
        print(f"✅ Completed processing {len(results)} sections in {elapsed:.2f} seconds")
        print(f"⚡ Average: {elapsed/len(results):.3f} seconds per section")
        return results
    
    def process_sections_with_processes(
        self,
        analyzer_func: Callable[[int, str, SectionMetadata], Dict[str, Any]],
        max_workers: int = 4,
        section_ids: Optional[List[int]] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        Process sections in parallel using ProcessPoolExecutor (single analyzer, optimized).
        Best for CPU-intensive regex operations that benefit from bypassing GIL.
        
        Args:
            analyzer_func: Function(section_id, content, metadata) -> analysis_result
            max_workers: Number of parallel processes
            section_ids: Specific sections to process (None = all sections)
            
        Returns:
            Dictionary mapping section_id to analysis results
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        # Determine which sections to process
        if section_ids is None:
            sections_to_process = self.sections
        else:
            sections_to_process = [s for s in self.sections if s.section_id in section_ids]
        
        results = {}
        total = len(sections_to_process)
        
        start_time = time.time()
        print(f"Processing {total} sections with {max_workers} process workers...")
        
        # Prepare arguments for worker function
        worker_args = [(section, str(self.file_path), analyzer_func) for section in sections_to_process]
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_section = {
                executor.submit(_process_section_worker, args): args[0].section_id
                for args in worker_args
            }
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_section):
                section_id = future_to_section[future]
                try:
                    worker_result = future.result()
                    results[section_id] = worker_result['result']
                    completed += 1
                    print(f"  ✓ Processed section {section_id} ({completed}/{total})")
                except Exception as e:
                    print(f"  ✗ Error processing section {section_id}: {e}")
                    results[section_id] = {"error": str(e)}
        
        elapsed = time.time() - start_time
        print(f"✅ Completed processing {len(results)} sections in {elapsed:.2f} seconds")
        print(f"⚡ Average: {elapsed/len(results):.3f} seconds per section")
        return results
    
    def process_sections_multi_analyzer(
        self,
        analyzer_configs: Dict[str, Dict[str, Any]],
        max_workers: int = 4,
        section_ids: Optional[List[int]] = None,
        use_processes: bool = False
    ) -> Dict[int, Dict[str, Any]]:
        """
        Process sections with MULTIPLE analyzers simultaneously for comparison.
        Each section gets analyzed by all enabled analyzers.
        
        Args:
            analyzer_configs: Dict of analyzer configurations:
                {
                    "simple": {
                        "func": simple_error_analyzer,
                        "enabled": True
                    },
                    "enhanced": {
                        "func": enhanced_error_analyzer,
                        "enabled": True
                    }
                }
            max_workers: Number of parallel threads/processes
            section_ids: Specific sections to process (None = all sections)
            use_processes: Use ProcessPoolExecutor for CPU-intensive tasks (default: False, uses ThreadPoolExecutor)
            
        Returns:
            Dictionary mapping section_id to results from all analyzers with timing
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        # Filter enabled analyzers
        enabled_analyzers = {
            name: config for name, config in analyzer_configs.items()
            if config.get("enabled", True)
        }
        
        if not enabled_analyzers:
            raise ValueError("No analyzers enabled!")
        
        executor_type = "processes" if use_processes else "threads"
        print(f"\n🔬 Multi-Analyzer Mode: {len(enabled_analyzers)} analyzers enabled ({executor_type})")
        for name in enabled_analyzers.keys():
            print(f"   • {name}")
        
        # Determine which sections to process
        if section_ids is None:
            sections_to_process = self.sections
        else:
            sections_to_process = [s for s in self.sections if s.section_id in section_ids]
        
        results = {}
        total = len(sections_to_process)
        
        start_time = time.time()
        print(f"\nProcessing {total} sections with {max_workers} workers...")
        
        def process_section_with_all_analyzers(section: SectionMetadata):
            """Run all enabled analyzers on one section."""
            content = self.extract_section(section.section_id)
            section_results = {
                'section_id': section.section_id,
                'section_name': section.section_name,
                'timestamp': section.timestamp,
                'analyzers': {}
            }
            
            for analyzer_name, config in enabled_analyzers.items():
                analyzer_func = config['func']
                analyzer_start = time.time()
                
                try:
                    result = analyzer_func(section.section_id, content, section)
                    analyzer_elapsed = time.time() - analyzer_start
                    
                    section_results['analyzers'][analyzer_name] = {
                        'result': result,
                        'execution_time_ms': round(analyzer_elapsed * 1000, 2),
                        'status': 'success'
                    }
                except Exception as e:
                    analyzer_elapsed = time.time() - analyzer_start
                    section_results['analyzers'][analyzer_name] = {
                        'error': str(e),
                        'execution_time_ms': round(analyzer_elapsed * 1000, 2),
                        'status': 'error'
                    }
            
            return section_results
        
        # Choose executor type: ProcessPoolExecutor for CPU-bound, ThreadPoolExecutor for I/O-bound
        ExecutorClass = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
        
        with ExecutorClass(max_workers=max_workers) as executor:
            # Submit all sections
            future_to_section = {
                executor.submit(process_section_with_all_analyzers, section): section.section_id
                for section in sections_to_process
            }
            
            # Collect results
            completed = 0
            for future in as_completed(future_to_section):
                section_id = future_to_section[future]
                try:
                    result = future.result()
                    results[section_id] = result
                    completed += 1
                    print(f"  ✓ Processed section {section_id} with {len(enabled_analyzers)} analyzers ({completed}/{total})")
                except Exception as e:
                    print(f"  ✗ Error processing section {section_id}: {e}")
                    results[section_id] = {"error": str(e)}
        
        elapsed = time.time() - start_time
        
        # Calculate performance stats
        print(f"\n✅ Completed processing {len(results)} sections in {elapsed:.2f} seconds")
        print(f"⚡ Average: {elapsed/len(results):.3f} seconds per section")
        
        # Analyzer performance comparison
        print(f"\n📊 Analyzer Performance Comparison:")
        analyzer_stats = {name: [] for name in enabled_analyzers.keys()}
        
        for section_result in results.values():
            if 'analyzers' in section_result:
                for analyzer_name, analyzer_data in section_result['analyzers'].items():
                    if analyzer_data.get('status') == 'success':
                        analyzer_stats[analyzer_name].append(analyzer_data['execution_time_ms'])
        
        for analyzer_name, times in analyzer_stats.items():
            if times:
                avg_time = sum(times) / len(times)
                min_time = min(times)
                max_time = max(times)
                print(f"   {analyzer_name:20s} → avg: {avg_time:6.2f}ms  min: {min_time:6.2f}ms  max: {max_time:6.2f}ms")
        
        return results
    
    def extract_all_sections(self, output_dir: str = "log_chunks") -> List[str]:
        """
        Extract all sections to separate files (use sparingly - creates many files).
        
        Args:
            output_dir: Directory to save chunk files
            
        Returns:
            List of output file paths
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        output_files = []
        base_name = self.file_path.stem
        
        for section in self.sections:
            section_id = section.section_id
            content = self.extract_section(section_id)
            
            output_file = output_path / f"{base_name}_section_{section_id:04d}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            output_files.append(str(output_file))
            
        print(f"Extracted {len(output_files)} sections to {output_dir}/")
        return output_files
    
    def search_sections(self, query: str, case_sensitive: bool = False) -> List[SectionMetadata]:
        """
        Search for sections by section_name or timestamp.
        
        Args:
            query: Text to search for
            case_sensitive: Whether search should be case sensitive
            
        Returns:
            List of matching sections
        """
        if not self.sections:
            raise ValueError("No sections indexed. Run create_index() first.")
        
        matches = []
        flags = 0 if case_sensitive else re.IGNORECASE
        search_pattern = re.compile(re.escape(query), flags)
        
        for section in self.sections:
            if search_pattern.search(section.section_name):
                matches.append(section)
            elif section.timestamp and search_pattern.search(section.timestamp):
                matches.append(section)
        
        print(f"Found {len(matches)} sections matching '{query}'")
        return matches
    
    def _extract_timestamp(self, header: str) -> Optional[str]:
        """Extract timestamp from header if present."""
        # Match common timestamp patterns like [03/08/2026 15:01:52]
        timestamp_pattern = r'\[(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\]'
        match = re.search(timestamp_pattern, header)
        return match.group(1) if match else None
    
    def _extract_section_name(self, header: str) -> str:
        """
        Extract section name from header.
        For pattern like: ********** [timestamp] path/to/file.log **********
        Returns: path/to/file.log
        """
        # Remove asterisks
        cleaned = re.sub(r'\*+', '', header).strip()
        
        # Remove timestamp in brackets
        cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
        
        # What remains should be the section identifier (file path, executable name, etc.)
        return cleaned if cleaned else "unknown"
    
    def print_summary(self):
        """Print a summary of indexed sections."""
        if not self.sections:
            print("No sections indexed yet.")
            return
        
        print(f"\n{'='*80}")
        print(f"Log Index Summary: {self.file_path.name}")
        print(f"{'='*80}")
        print(f"Total sections: {len(self.sections)}")
        print(f"Total size: {sum(s.size_bytes for s in self.sections):,} bytes")
        print(f"\nFirst 10 sections:")
        
        for section in self.sections[:10]:
            ts = section.timestamp or "no-timestamp"
            print(f"  [{section.section_id:3d}] {ts} | {section.section_name[:50]}")
        
        if len(self.sections) > 10:
            print(f"  ... and {len(self.sections) - 10} more sections")
        print(f"{'='*80}\n")


# ==================== Worker Functions for Multiprocessing ====================

def _process_section_worker(args):
    """
    Top-level worker function for ProcessPoolExecutor.
    Must be at module level to be picklable.
    """
    section, file_path, analyzer_func = args
    
    # Read section content
    line_start, line_end = section.line_range
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        content = ''.join(lines[line_start - 1:line_end])
    
    # Run analyzer
    try:
        result = analyzer_func(section.section_id, content, section)
        return {
            'section_id': section.section_id,
            'result': result,
            'status': 'success'
        }
    except Exception as e:
        return {
            'section_id': section.section_id,
            'error': str(e),
            'status': 'error'
        }


# ==================== Example Analyzer Functions ====================

def extract_context_around_line(content: str, target_line_num: int, context_lines: int = 100) -> str:
    """
    Extract ±context_lines around a specific line number for summary.
    
    Args:
        content: Full section content
        target_line_num: Line number to extract context around (1-indexed)
        context_lines: Number of lines before and after to include
        
    Returns:
        Context string (max 1000 chars)
    """
    lines = content.split('\n')
    start_idx = max(0, target_line_num - context_lines - 1)
    end_idx = min(len(lines), target_line_num + context_lines)
    
    context = '\n'.join(lines[start_idx:end_idx])
    # Limit to 1000 chars for reasonable summary size
    return context[:1000] if len(context) > 1000 else context


def extract_anchors_with_context(content: str, pattern: str, section_start_line: int, max_anchors: int = 50) -> Dict[str, Any]:
    """
    Extract error/warning anchors with line numbers, messages, counts, and context summaries.
    Returns anchors sorted by count in descending order.
    
    Args:
        content: Log content to analyze
        pattern: Regex pattern to match (e.g., 'error', 'warning')
        section_start_line: Starting line number of this section in the full log
        max_anchors: Maximum number of unique anchors to return
        
    Returns:
        Dict with unique count and anchors array sorted by count (descending)
    """
    lines = content.split('\n')
    regex = re.compile(pattern, re.IGNORECASE)
    
    # Track: message -> [line_numbers, first_occurrence_content]
    message_tracker = {}
    
    for idx, line in enumerate(lines):
        if regex.search(line):
            cleaned = line.strip()[:500]  # Max 500 chars per message
            if cleaned:
                abs_line_num = section_start_line + idx
                if cleaned not in message_tracker:
                    # Store first occurrence
                    message_tracker[cleaned] = {
                        'first_line': abs_line_num,
                        'first_idx': idx,
                        'count': 1
                    }
                else:
                    message_tracker[cleaned]['count'] += 1
    
    # Build anchors array
    anchors = []
    for message, info in message_tracker.items():
        # Extract context around first occurrence
        context = extract_context_around_line(content, info['first_idx'] + 1, context_lines=100)
        
        anchors.append({
            'Ln#': str(info['first_line']),
            'Str': message,
            'Cnt': info['count'],
            'Log': context
        })
    
    # Sort by count descending (reverse order)
    anchors.sort(key=lambda x: x['Cnt'], reverse=True)
    
    # Limit to max_anchors
    anchors = anchors[:max_anchors]
    
    return {
        'uniques': len(message_tracker),
        'anchors': anchors
    }


def extract_unique_messages(content: str, pattern: str, max_unique: int = 20) -> Dict[str, Any]:
    """
    Extract unique error/warning messages from content.
    
    Args:
        content: Log content to analyze
        pattern: Regex pattern to match (e.g., 'error', 'warning')
        max_unique: Maximum number of unique messages to keep
        
    Returns:
        Dict with count, unique messages, and their frequencies
    """
    lines = content.split('\n')
    matching_lines = []
    
    # Find all lines containing the pattern
    regex = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        if regex.search(line):
            # Clean up the line (strip whitespace, limit length)
            cleaned = line.strip()[:500]  # Max 500 chars per message
            if cleaned:
                matching_lines.append(cleaned)
    
    # Count occurrences of each unique message
    message_counts = Counter(matching_lines)
    
    # Get most common unique messages
    unique_messages = []
    for message, count in message_counts.most_common(max_unique):
        unique_messages.append({
            'message': message,
            'count': count
        })
    
    return {
        'total_count': len(matching_lines),
        'unique_count': len(message_counts),
        'top_messages': unique_messages
    }


def minimal_analyzer(section_id: int, content: str, metadata: SectionMetadata) -> Dict[str, Any]:
    """
    Analyzer that outputs in the exact demo.json format with anchors.
    Fast, no LLM calls - just regex + context extraction.
    Uses ThreadPoolExecutor to parallelize error types within each section.
    Only includes categories with at least 1 unique entry (excludes empty categories).
    """
    error_patterns = {
        'errors': r'\berror\b',
        'warnings': r'\bwarning\b',
        'exceptions': r'\bexception\b',
        'failures': r'\bfail(ed|ure)?\b'
    }
    
    # Get starting line number for this section
    section_start_line = metadata.line_range[0]
    
    results = {}
    
    # Process error types in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all error type tasks
        future_to_error_type = {
            executor.submit(
                extract_anchors_with_context,
                content=content,
                pattern=pattern,
                section_start_line=section_start_line,
                max_anchors=50
            ): error_type
            for error_type, pattern in error_patterns.items()
        }
        
        # Collect results as they complete - only include non-empty categories
        for future in as_completed(future_to_error_type):
            error_type = future_to_error_type[future]
            try:
                result = future.result()
                # Only add to results if there are actual entries (uniques > 0)
                if result['uniques'] > 0:
                    results[error_type] = result
            except Exception as e:
                # Skip errors - don't add empty entries
                pass
    
    return results

# ==================== Example Usage ====================

if __name__ == "__main__":
    total_start = time.time()
    
    # ========== DEBUG CONFIGURATION ==========
    # Set to limit processing to first N sections (None = process all)
    DEBUG_LIMIT = None  # Change to None to process all sections
    # =========================================
    
    # Pattern for your specific log format
    # ****************** [date time] path ******************
    header_pattern = r'\*{10,}\s+\[.*?\]\s+.*?\s+\*{10,}'
    
    # Or for executable-style headers: r'\[EXECUTABLE:\s+.*?\]'
    
    # Step 1: Create lightweight index
    chunker = LogChunker("ERR_LOG_1/combinedlog.txt", header_pattern)
    sections = chunker.create_index()
    chunker.print_summary()
    
    # Step 2: Determine optimal process count
    # ProcessPool for sections × ThreadPool (4 workers) for error types within each section
    cpu_count = os.cpu_count() or 4
    optimal_workers = min(8, cpu_count)
    print(f"\n💡 System has {cpu_count} CPUs, using {optimal_workers} process workers")
    print(f"   2-level parallelism: {optimal_workers} processes × 4 threads = {optimal_workers * 4} concurrent tasks")
    
    # Step 3: Configure analyzer
    print("\n" + "="*80)
    print("🚀 Using optimized single-analyzer mode with ProcessPoolExecutor")
    print("   Analyzer: minimal_analyzer (demo format with 2-level parallelism)")
    print("   • Outer: Processes for sections (bypasses GIL)")
    print("   • Inner: Threads for error types (4 parallel per section)")
    print("="*80)
    
    # Step 4: Process sections with process pool
    # Apply DEBUG_LIMIT if set
    if DEBUG_LIMIT is not None:
        section_ids_to_process = [s.section_id for s in sections[:DEBUG_LIMIT]]
        print(f"\n🐛 DEBUG MODE: Processing first {DEBUG_LIMIT} sections")
    else:
        section_ids_to_process = None
        print(f"\nProcessing ALL {len(sections)} sections")
    
    results = chunker.process_sections_with_processes(
        analyzer_func=minimal_analyzer,
        max_workers=optimal_workers,
        section_ids=section_ids_to_process
    )
    
    # Step 5: Save everything to a single unified JSON
    output_file = chunker.save_unified_json(
        analysis_results=results,
        output_path="log_analysis.json",
        is_multi_analyzer=False,  # Single analyzer mode
        demo_format=True  # Use compact demo.json format
    )
    
    # Show sample result
    if results:
        sample_id = list(results.keys())[0]
        sample_result = results[sample_id]
        print(f"\nSample result for section {sample_id}:")
        if 'errors' in sample_result:
            print(f"  Errors: {sample_result['errors']['uniques']} unique")
        if 'warnings' in sample_result:
            print(f"  Warnings: {sample_result['warnings']['uniques']} unique")
        if 'exceptions' in sample_result:
            print(f"  Exceptions: {sample_result['exceptions']['uniques']} unique")
        if 'failures' in sample_result:
            print(f"  Failures: {sample_result['failures']['uniques']} unique")
    
    total_elapsed = time.time() - total_start
    
    print("\n" + "="*80)
    if DEBUG_LIMIT is not None:
        print(f"✅ Complete! Analyzed {len(results)} sections (DEBUG MODE: limited to first {DEBUG_LIMIT})")
    else:
        print("✅ Complete! All sections analyzed successfully")
    print(f"   Output file: {output_file}")
    print(f"   Total sections in file: {len(sections)}")
    print(f"   Analyzed sections: {len(results)}")
    print(f"   Workers used: {optimal_workers} processes")
    print(f"   ⏱️  Total execution time: {total_elapsed:.2f} seconds ({total_elapsed/60:.2f} minutes)")
    print(f"   ⚡ Throughput: {len(results)/total_elapsed:.2f} sections/second")
    print("="*80)
    if DEBUG_LIMIT is not None:
        print(f"\n🐛 DEBUG MODE ACTIVE: Only first {DEBUG_LIMIT} sections processed")
        print("   To process all sections, set DEBUG_LIMIT = None at the top of the script")
    print("\nParallel Processing Architecture (2-Level):")
    print("  • Level 1 (Outer): ProcessPoolExecutor - sections processed across CPU cores")
    print("  • Level 2 (Inner): ThreadPoolExecutor - 4 error types per section in parallel")
    print(f"  • Total parallelism: {optimal_workers} processes × 4 threads = {optimal_workers * 4} concurrent tasks")
    print("\nOutput Format:")
    print("  • Compact demo.json format with id, name, ts, lines")
    print("  • Each section has: errors, warnings, exceptions, failures")
    print("  • Anchors sorted by count (descending) with Ln#, Str, Cnt, Log fields")
    print("="*80)
