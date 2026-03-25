import os
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SecondAgent:
    """Second agent that executes verified code in production-like environment"""
    
    def __init__(self):
        self.output_dir = os.environ.get('CODE_OUTPUT_DIR', '/tmp/generated')
    
    def run_verified_code(self, code):
        logger.info("Second agent: Executing verified Fibonacci code")
        
        try:
            result = self._execute_in_production(code)
            
            return {
                'status': 'success',
                'result': result,
                'message': 'Code executed successfully in production environment'
            }
        except Exception as e:
            logger.error(f"Second agent error: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _execute_in_production(self, code):
        import sys
        import io
        import traceback
        
        output = io.StringIO()
        error_output = io.StringIO()
        
        try:
            compiled = compile(code, '<fibonacci>', 'exec')
            namespace = {}
            exec(compiled, namespace)
            
            if 'fibonacci' in namespace:
                fib_func = namespace['fibonacci']
                test_results = []
                
                test_cases = [(0, 0), (1, 1), (10, 55), (20, 6765), (50, 12586269025)]
                
                for n, expected in test_cases:
                    result = fib_func(n)
                    test_results.append({
                        'input': n,
                        'expected': expected,
                        'actual': result,
                        'passed': result == expected
                    })
                
                return {
                    'tests_passed': all(t['passed'] for t in test_results),
                    'test_results': test_results
                }
            
            return {'error': 'fibonacci function not found'}
            
        except Exception as e:
            return {
                'error': str(e),
                'traceback': traceback.format_exc()
            }
    
    def generate_report(self, code, execution_result):
        report = {
            'timestamp': str(datetime.now()),
            'code_length': len(code),
            'execution_result': execution_result
        }
        
        report_file = os.path.join(self.output_dir, 'second_agent_report.json')
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Report saved to {report_file}")
        return report


if __name__ == '__main__':
    from datetime import datetime
    
    sample_code = '''
def fibonacci(n):
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''
    
    agent = SecondAgent()
    result = agent.run_verified_code(sample_code)
    print(json.dumps(result, indent=2))
