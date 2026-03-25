#!/usr/bin/env python3
"""
Dynamic Code Execution Pipeline

This module provides the main CLI entry point for executing Python code
in a Gvisor-sandboxed Kubernetes environment with security analysis
and automatic evaluation.

Usage:
    # Kubernetes mode (default)
    python run_dynamic.py --task "reverse a string"
    python run_dynamic.py --prompt "Generate a function that sorts a list"
    python run_dynamic.py --code "print('hello')"

    # Local mode (legacy)
    KUBERNETES_MODE=false python run_dynamic.py --task "reverse a string"

Environment Variables (Kubernetes mode):
    TASK: Task description for LLM code generation
    PROMPT: Custom prompt for LLM code generation
    CODE: Direct Python code to execute

Exit Codes:
    0: Success - all tests passed
    1: Failure - security check failed, execution error, or test failure
"""

import os
import sys
import logging

from typing import Optional, Dict, Any, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_code_from_input(is_kubernetes: bool) -> Optional[str]:
    """
    Get code from environment variables (K8s) or CLI arguments (local).
    
    Args:
        is_kubernetes: Whether running in Kubernetes mode
        
    Returns:
        Code string or None if no input provided
    """
    if is_kubernetes:
        code = os.environ.get('CODE')
        task = os.environ.get('TASK')
        prompt = os.environ.get('PROMPT')
        
        if code:
            logger.info("Using CODE from environment")
            return code
        elif task:
            logger.info(f"Generating code for task: {task}")
            from agent.langchain_agent import CodeGenerationAgent
            agent = CodeGenerationAgent()
            return agent.generate_code_from_task(task)
        elif prompt:
            logger.info("Generating code from PROMPT")
            from agent.langchain_agent import CodeGenerationAgent
            agent = CodeGenerationAgent()
            return agent.generate_code(prompt)
        else:
            logger.error("Set TASK, PROMPT, or CODE env var")
            return None
    else:
        import argparse
        parser = argparse.ArgumentParser(
            description='Dynamic code generation and execution'
        )
        parser.add_argument(
            '--task',
            type=str,
            help='Task description for code generation'
        )
        parser.add_argument(
            '--prompt',
            type=str,
            help='Full prompt for code generation'
        )
        parser.add_argument(
            '--code',
            type=str,
            help='Direct code to execute (skip generation)'
        )
        args = parser.parse_args()
        
        if args.code:
            logger.info("Using provided code directly")
            return args.code
        elif args.task:
            logger.info(f"Generating code for task: {args.task}")
            from agent.langchain_agent import CodeGenerationAgent
            agent = CodeGenerationAgent()
            return agent.generate_code_from_task(args.task)
        elif args.prompt:
            logger.info("Generating code from custom prompt")
            from agent.langchain_agent import CodeGenerationAgent
            agent = CodeGenerationAgent()
            return agent.generate_code(args.prompt)
        else:
            logger.error("Please provide --task, --prompt, or --code")
            return None


def run_security_analysis(code: str) -> Tuple[bool, Any]:
    """
    Run security analysis on the code.
    
    Args:
        code: Python code to analyze
        
    Returns:
        Tuple of (is_safe, report)
    """
    logger.info("Step 1: Security Analysis")
    from security.security_analyzer import SecurityAnalyzer
    analyzer = SecurityAnalyzer()
    is_safe, report = analyzer.analyze(code)
    logger.info(f"Safe: {is_safe}")
    logger.info(f"Report: {report}")
    return is_safe, report


def run_sandbox_execution(code: str) -> Dict[str, Any]:
    """
    Execute code in Gvisor sandbox.
    
    Args:
        code: Python code to execute
        
    Returns:
        Execution result dict
    """
    logger.info("Step 2: Sandbox Execution")
    from sandbox.gvisor_executor import GvisorSandboxExecutor
    executor = GvisorSandboxExecutor()
    result = executor.execute(code)
    
    logger.info(f"Success: {result['success']}")
    logger.info(f"Output: {result['output']}")
    if result.get('error'):
        logger.error(f"Error: {result['error']}")
    
    return result


def run_evaluation(code: str, execution_output: str) -> Dict[str, Any]:
    """
    Evaluate code against auto-generated tests.
    
    Args:
        code: Python code that was executed
        execution_output: Output from execution
        
    Returns:
        Evaluation result dict
    """
    logger.info("Step 3: Code Evaluation")
    from evaluation.evaluator import CodeEvaluator
    evaluator = CodeEvaluator()
    eval_result = evaluator.evaluate(code, execution_output)
    
    logger.info(
        f"Tests Passed: {eval_result['passed_tests']}/{eval_result['total_tests']}"
    )
    for test in eval_result['test_results']:
        status = "PASS" if test['passed'] else "FAIL"
        logger.info(f"  [{status}] {test['name']}: {test.get('actual', 'N/A')}")
    
    return eval_result


def main() -> None:
    """Main entry point for the dynamic code execution pipeline."""
    is_kubernetes = os.environ.get('KUBERNETES_MODE', 'true').lower() == 'true'
    
    logger.info("=" * 50)
    logger.info("Dynamic Code Execution Pipeline")
    logger.info(f"Mode: {'Kubernetes' if is_kubernetes else 'Local'}")
    logger.info("=" * 50)
    
    code = get_code_from_input(is_kubernetes)
    
    if code is None:
        sys.exit(1)
    
    logger.info(f"\nGenerated code:\n{code}")
    
    is_safe, report = run_security_analysis(code)
    
    if not is_safe:
        logger.error("Code failed security check!")
        sys.exit(1)
    
    exec_result = run_sandbox_execution(code)
    
    if not exec_result['success']:
        logger.error("Code execution failed")
        sys.exit(1)
    
    eval_result = run_evaluation(code, exec_result.get('output', ''))
    
    if eval_result['passed']:
        logger.info(
            "\nSUCCESS: All tests passed! "
            "Code executed and verified in Gvisor sandbox."
        )
    else:
        logger.warning("\nWARNING: Some tests failed")
        sys.exit(1)


if __name__ == '__main__':
    main()