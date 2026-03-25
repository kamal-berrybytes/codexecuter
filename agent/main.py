import os
import sys
import json
import yaml
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KUBERNETES_MODE = os.environ.get('KUBERNETES_MODE', 'false').lower() == 'true'


def run_in_kubernetes():
    import subprocess
    logger.info("Running in Kubernetes mode")
    
    namespace = os.environ.get('NAMESPACE', 'fibonacci-agent')
    code_configmap = os.environ.get('CODE_CONFIGMAP', 'generated-code')
    results_configmap = os.environ.get('RESULTS_CONFIGMAP', 'execution-results')
    
    try:
        logger.info("Step 1: Running code generation agent")
        subprocess.run([
            'python', '/app/agent/langchain_agent.py'
        ], check=True)
        
        logger.info("Step 2: Running security analysis")
        subprocess.run([
            'python', '/app/security/security_analyzer.py'
        ], check=True)
        
        logger.info("Step 3: Running sandbox execution")
        subprocess.run([
            'python', '/app/sandbox/gvisor_executor.py'
        ], check=True)
        
        logger.info("Step 4: Running evaluation")
        subprocess.run([
            'python', '/app/evaluation/evaluator.py'
        ], check=True)
        
        logger.info("Step 5: Running second agent with verified code")
        subprocess.run([
            'python', '/app/agent/second_agent.py'
        ], check=True)
        
        logger.info("All steps completed successfully!")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Step failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


def run_local():
    logger.info("Running in local mode")
    
    from agent.langchain_agent import CodeGenerationAgent
    from security.security_analyzer import SecurityAnalyzer
    from sandbox.gvisor_executor import GvisorSandboxExecutor
    from evaluation.evaluator import CodeEvaluator
    from agent.second_agent import SecondAgent
    
    try:
        logger.info("Step 1: Generating Fibonacci code")
        agent = CodeGenerationAgent()
        generated_code = agent.generate_fibonacci_code()
        logger.info(f"Generated code:\n{generated_code}")
        
        logger.info("Step 2: Analyzing code for security")
        analyzer = SecurityAnalyzer()
        is_safe, report = analyzer.analyze(generated_code)
        logger.info(f"Security analysis: {report}")
        
        if not is_safe:
            logger.error("Code failed security check!")
            return False
        
        logger.info("Step 3: Executing in Gvisor sandbox")
        executor = GvisorSandboxExecutor()
        result = executor.execute(generated_code)
        logger.info(f"Execution result: {result}")
        
        logger.info("Step 4: Evaluating output")
        evaluator = CodeEvaluator()
        evaluation_result = evaluator.evaluate(generated_code, result['output'])
        logger.info(f"Evaluation result: {evaluation_result}")
        
        if not evaluation_result['passed']:
            logger.error("Code failed evaluation!")
            return False
        
        logger.info("Step 5: Running second agent with verified code")
        second_agent = SecondAgent()
        final_result = second_agent.run_verified_code(generated_code)
        logger.info(f"Second agent result: {final_result}")
        
        logger.info("All steps completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


def main():
    logger.info("Starting Fibonacci Code Agent")
    logger.info(f"Kubernetes mode: {KUBERNETES_MODE}")
    
    if KUBERNETES_MODE:
        success = run_in_kubernetes()
    else:
        success = run_local()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
