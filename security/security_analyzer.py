"""
Security Analyzer for Gvisor Code Execution Platform

This module provides the SecurityAnalyzer class for detecting
potentially dangerous code patterns before execution.

Security Checks:
- Execution: subprocess, os.system, eval, exec, compile
- Network: socket, urllib, requests, http
- Filesystem: os.chmod, os.remove, open(w/a), shutil
- Code Loading: __import__, pickle, yaml.load, marshal
- Runtime: globals, locals, vars, dynamic modules

Usage:
    from security.security_analyzer import SecurityAnalyzer
    
    analyzer = SecurityAnalyzer()
    is_safe, report = analyzer.analyze(code)
    
    if not is_safe:
        print(f"Security issues: {report['issues']}")
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DANGEROUS_PATTERNS = [
    (r'subprocess\.(run|Popen|call|check_output)', 'subprocess execution'),
    (r'os\.system\s*\(', 'os.system call'),
    (r'eval\s*\(', 'eval function'),
    (r'exec\s*\(', 'exec function'),
    (r'compile\s*\(', 'compile function'),
    (r'__import__\s*\(', 'dynamic import'),
    (r'os\.popen\s*\(', 'os.popen'),
    (r'pty\.', 'pty module'),
    (r'socket\.', 'socket module'),
    (r'urllib\.', 'network request'),
    (r'requests\.', 'HTTP requests'),
    (r'http\.', 'HTTP module'),
    (r'os\.chmod\s*\(', 'chmod'),
    (r'os\.chown\s*\(', 'chown'),
    (r'os\.makedirs\s*\(', 'makedirs'),
    (r'os\.remove\s*\(', 'remove file'),
    (r'os\.unlink\s*\(', 'unlink file'),
    (r'shutil\.rmtree\s*\(', 'rmtree'),
    (r'open\s*\([^)]*,\s*["\']w', 'write file'),
    (r'open\s*\([^)]*,\s*["\']a', 'append file'),
    (r'fileinput\.', 'fileinput'),
    (r'yaml\.load\s*\(', 'yaml.load'),
    (r'pickle\.load\s*\(', 'pickle.load'),
    (r'marshal\.load\s*\(', 'marshal.load'),
    (r'module\s*=', 'dynamic module'),
    (r'globals\s*\(', 'globals'),
    (r'locals\s*\(', 'locals'),
    (r'vars\s*\(', 'vars'),
]

ALLOWED_IMPORTS = {
    'math', 'random', 'datetime', 'time', 'json', 're', 'functools',
    'itertools', 'collections', 'operator', 'typing', 'sys', 'os.path',
    'pytest', 'unittest', 'abc', 'copy', 'bisect', 'array'
}


class SecurityAnalyzer:
    """
    Analyzes Python code for dangerous patterns before execution.
    
    Scans for:
    - Code execution (subprocess, eval, exec)
    - Network access (socket, urllib, requests)
    - File operations (open for write, os.remove)
    - Dynamic code loading (pickle, marshal, yaml.load)
    
    Attributes:
        dangerous_patterns: List of (regex, description) tuples
        allowed_imports: Set of permitted import modules
    """
    
    def __init__(
        self,
        dangerous_patterns: List[Tuple[str, str]] = None,
        allowed_imports: set = None
    ):
        self.dangerous_patterns = dangerous_patterns or DANGEROUS_PATTERNS
        self.allowed_imports = allowed_imports or ALLOWED_IMPORTS
    
    def analyze(self, code: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Analyze code for security vulnerabilities.
        
        Args:
            code: Python code to analyze
            
        Returns:
            Tuple of (is_safe: bool, report: dict)
            
        Report dict contains:
            - is_safe: bool
            - issues: List[dict] of detected issues
            - lines_of_code: int
        """
        logger.info("Analyzing code for security vulnerabilities")
        
        issues: List[Dict[str, Any]] = []
        
        for pattern, description in self.dangerous_patterns:
            matches = re.findall(pattern, code, re.IGNORECASE)
            if matches:
                issues.append({
                    'pattern': pattern,
                    'description': description,
                    'matches': matches[:3]
                })
        
        import_issues = self._check_imports(code)
        issues.extend(import_issues)
        
        is_safe = len(issues) == 0
        
        report: Dict[str, Any] = {
            'is_safe': is_safe,
            'issues': issues,
            'lines_of_code': len(code.split('\n'))
        }
        
        self._save_report(report)
        
        logger.info(f"Security analysis complete. Safe: {is_safe}")
        return is_safe, report
    
    def _check_imports(self, code: str) -> List[Dict[str, Any]]:
        """Check for disallowed imports."""
        issues: List[Dict[str, Any]] = []
        
        import_pattern = r'^(?:from\s+(\S+)\s+import|import\s+(\S+))'
        
        for line in code.split('\n'):
            line = line.strip()
            if line.startswith('#'):
                continue
            
            match = re.match(import_pattern, line)
            if match:
                module = match.group(1) or match.group(2)
                base_module = module.split('.')[0]
                
                if base_module not in self.allowed_imports:
                    if base_module not in ['fibonacci', 'TestFibonacci']:
                        issues.append({
                            'pattern': f'import {module}',
                            'description': f'non-standard import: {base_module}',
                            'matches': [line]
                        })
        
        return issues
    
    def _save_report(self, report: Dict[str, Any]) -> None:
        """Save security report to file."""
        output_dir = os.environ.get('CODE_OUTPUT_DIR', '/tmp/generated')
        os.makedirs(output_dir, exist_ok=True)
        
        report_file = os.path.join(output_dir, 'security_report.json')
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Security report saved to {report_file}")


if __name__ == '__main__':
    analyzer = SecurityAnalyzer()
    
    test_code = '''
import subprocess
os.system("ls")
eval("1+1")
'''
    
    is_safe, report = analyzer.analyze(test_code)
    print(f"Is safe: {is_safe}")
    print(f"Issues: {report['issues']}")