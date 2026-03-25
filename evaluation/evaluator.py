import os
import sys
import json
import logging
import subprocess
import re
import tempfile
import time

import yaml

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CodeEvaluator:
    """Evaluates generated code against test cases using Semgrep"""

    def __init__(self, output_dir=None):
        self.output_dir = output_dir or os.environ.get(
            "CODE_OUTPUT_DIR", "/tmp/generated"
        )
        self.timeout = int(os.environ.get("EXECUTION_TIMEOUT", "30"))
        self.use_kubernetes = (
            os.environ.get("KUBERNETES_MODE", "true").lower() == "true"
        )

    def evaluate(self, code, execution_output=None, test_cases=None):
        logger.info("Evaluating code with Semgrep")

        if test_cases is None:
            test_cases = self._auto_generate_tests(code)

        results = []
        all_passed = True

        for test_case in test_cases:
            result = self._run_test(code, test_case)
            results.append(result)
            if not result["passed"]:
                all_passed = False

        semgrep_results = self._run_semgrep(code)

        evaluation = {
            "passed": all_passed,
            "total_tests": len(test_cases),
            "passed_tests": sum(1 for r in results if r["passed"]),
            "failed_tests": sum(1 for r in results if not r["passed"]),
            "test_results": results,
            "semgrep_analysis": semgrep_results,
        }

        self._save_evaluation(evaluation)

        logger.info(
            f"Evaluation complete. Passed: {evaluation['passed_tests']}/{evaluation['total_tests']}"
        )

        return evaluation

    def _run_semgrep(self, code):
        """Run Semgrep analysis on the code in a Kubernetes pod"""
        os.makedirs(self.output_dir, exist_ok=True)
        code_file = os.path.join(self.output_dir, "code.py")
        with open(code_file, "w") as f:
            f.write(code)

        pod_name = f"semgrep-analyzer-{int(time.time())}"

        pod_spec = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": os.environ.get("NAMESPACE", "fibonacci-agent"),
            },
            "spec": {
                "restartPolicy": "Never",
                "runtimeClassName": os.environ.get("RUNTIME_CLASS", "gvisor"),
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                },
                "containers": [
                    {
                        "name": "semgrep",
                        "image": "fibonacci-agent:latest",
                        "imagePullPolicy": "Never",
                        "command": [
                            "sh",
                            "-c",
                            
                            # "python -m venv /tmp/venv && /tmp/venv/bin/pip install semgrep && /tmp/venv/bin/semgrep scan --json /tmp/code/code.py && ls -la /tmp/code/ && cat /tmp/code/code.py",
                            "python -m venv /tmp/venv && /tmp/venv/bin/pip install semgrep && /tmp/venv/bin/semgrep scan --json --verbose /tmp/code/code.py && ls -la /tmp/code/ && cat /tmp/code/code.py",
                        ],
                        "securityContext": {
                            "readOnlyRootFilesystem": False,
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [{"name": "code", "mountPath": "/tmp/code"}],
                    }
                ],
                "volumes": [
                    {
                        "name": "code",
                        "persistentVolumeClaim": {"claimName": "generated-code-pvc"},
                    }
                ],
            },
        }

        namespace = os.environ.get("NAMESPACE", "fibonacci-agent")

        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "-n", namespace],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        pod_file = os.path.join(self.output_dir, "semgrep-pod.yaml")
        with open(pod_file, "w") as f:
            yaml.dump(pod_spec, f)

        result = subprocess.run(
            ["kubectl", "apply", "-f", pod_file, "-n", namespace],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to create semgrep pod: {result.stderr}")
            return self._run_semgrep_local(code)

        return self._wait_for_semgrep(pod_name, namespace)

    def _wait_for_semgrep(self, pod_name, namespace):
        """Wait for semgrep pod to complete"""
        max_wait = 60
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                result = subprocess.run(
                    ["kubectl", "get", "pod", pod_name, "-n", namespace, "-o", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    pod_data = json.loads(result.stdout)
                    phase = pod_data.get("status", {}).get("phase", "Pending")

                    if phase == "Succeeded":
                        logs_result = subprocess.run(
                            ["kubectl", "logs", pod_name, "-n", namespace],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )

                        return self._parse_semgrep_output(logs_result.stdout)

                    elif phase == "Failed":
                        logs_result = subprocess.run(
                            ["kubectl", "logs", pod_name, "-n", namespace],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        return {
                            "success": False,
                            "findings": [],
                            "findings_count": 0,
                            "error": logs_result.stdout or "Pod failed",
                        }

                time.sleep(2)

            except Exception as e:
                logger.warning(f"Error checking semgrep pod status: {e}")
                time.sleep(2)

        return {
            "success": False,
            "findings": [],
            "findings_count": 0,
            "error": "Timeout",
        }

    def _parse_semgrep_output(self, output):
        """Parse semgrep JSON output"""
        findings = []
        if output:
            try:
                data = json.loads(output)
                results_list = data.get("results", [])
                for finding in results_list:
                    findings.append(
                        {
                            "rule_id": finding.get("check_id", ""),
                            "message": finding.get("extra", {}).get("message", ""),
                            "severity": finding.get("extra", {}).get("severity", ""),
                            "file": finding.get("path", ""),
                            "line": finding.get("start", {}).get("line", 0),
                        }
                    )
            except json.JSONDecodeError:
                pass

        return {"success": True, "findings": findings, "findings_count": len(findings)}

    def _run_semgrep_local(self, code):
        """Fallback: run semgrep locally (for testing)"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            code_file = f.name

        try:
            result = subprocess.run(
                ["semgrep", "--json", "--quiet", code_file],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return self._parse_semgrep_output(result.stdout)
        except Exception as e:
            return {
                "success": False,
                "findings": [],
                "findings_count": 0,
                "error": str(e),
            }

    def _auto_generate_tests(self, code):
        test_cases = []

        function_names = self._extract_functions(code)

        for func_name in function_names:
            test_cases.extend(self._generate_tests_for_function(code, func_name))

        if not test_cases:
            test_cases = [
                {
                    "name": "test_execution",
                    "input": None,
                    "expected": None,
                    "check": "runs",
                }
            ]

        return test_cases

    def _extract_functions(self, code):
        functions = []

        pattern = r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        matches = re.findall(pattern, code)
        functions.extend(matches)

        class_pattern = r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:\(]"
        classes = re.findall(class_pattern, code)

        return functions

    def _generate_tests_for_function(self, code, func_name):
        tests = []

        if "fibonacci" in func_name.lower():
            tests = [
                {"name": f"{func_name}_0", "input": 0, "expected": 0},
                {"name": f"{func_name}_1", "input": 1, "expected": 1},
                {"name": f"{func_name}_10", "input": 10, "expected": 55},
                {"name": f"{func_name}_20", "input": 20, "expected": 6765},
            ]
        elif "reverse" in func_name.lower() and "string" in code.lower():
            tests = [
                {"name": f"{func_name}_abc", "input": "abc", "expected": "cba"},
                {"name": f"{func_name}_empty", "input": "", "expected": ""},
                {"name": f"{func_name}_single", "input": "a", "expected": "a"},
            ]
        elif "sort" in func_name.lower():
            tests = [
                {
                    "name": f"{func_name}_unsorted",
                    "input": [3, 1, 2],
                    "expected": [1, 2, 3],
                },
                {"name": f"{func_name}_empty", "input": [], "expected": []},
                {"name": f"{func_name}_single", "input": [1], "expected": [1]},
            ]
        elif "factorial" in func_name.lower():
            tests = [
                {"name": f"{func_name}_0", "input": 0, "expected": 1},
                {"name": f"{func_name}_1", "input": 1, "expected": 1},
                {"name": f"{func_name}_5", "input": 5, "expected": 120},
            ]
        elif "prime" in func_name.lower():
            tests = [
                {"name": f"{func_name}_2", "input": 2, "expected": True},
                {"name": f"{func_name}_3", "input": 3, "expected": True},
                {"name": f"{func_name}_4", "input": 4, "expected": False},
                {"name": f"{func_name}_17", "input": 17, "expected": True},
            ]
        else:
            tests = [
                {
                    "name": f"{func_name}_basic",
                    "input": None,
                    "expected": None,
                    "check": "runs",
                }
            ]

        return tests

    def evaluate_with_custom_tests(self, code, custom_tests):
        return self.evaluate(code, test_cases=custom_tests)

    def _run_test(self, code, test_case):
        import io
        import traceback

        output = io.StringIO()
        error_output = io.StringIO()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = output
        sys.stderr = error_output

        result = {
            "name": test_case.get("name", "test"),
            "input": test_case.get("input"),
            "expected": test_case.get("expected"),
            "passed": False,
            "actual": None,
            "error": None,
        }

        try:
            compiled = compile(code, "<generated>", "exec")
            namespace = {"__name__": "__test__"}
            exec(compiled, namespace)

            if test_case.get("check") == "runs":
                result["passed"] = True
                result["actual"] = "executed successfully"
            else:
                func_name = test_case["name"].split("_")[0]
                if len(test_case["name"].split("_")) > 1:
                    func_name = test_case["name"].rsplit("_", 1)[0].rsplit("_", 1)[0]

                for name in namespace:
                    if not name.startswith("_") and callable(namespace[name]):
                        func = namespace[name]
                        if callable(func):
                            try:
                                input_val = test_case["input"]
                                actual = func(input_val)
                                result["actual"] = actual

                                if test_case.get("expected") is not None:
                                    result["passed"] = actual == test_case["expected"]
                                else:
                                    result["passed"] = True
                                break
                            except Exception:
                                continue
                else:
                    result["error"] = "No callable function found"

        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)}"
            result["passed"] = False

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        return result

    def _save_evaluation(self, evaluation):
        eval_file = os.path.join(self.output_dir, "evaluation_result.json")

        with open(eval_file, "w") as f:
            json.dump(evaluation, f, indent=2)

        logger.info(f"Evaluation result saved to {eval_file}")

    def _run_pytest(self, code_file):
        try:
            result = subprocess.run(
                ["pytest", code_file, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            return {
                "passed": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "", "error": "Test execution timeout"}
        except Exception as e:
            return {"passed": False, "output": "", "error": str(e)}


if __name__ == "__main__":
    sample_code = """
def fibonacci(n):
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
"""

    evaluator = CodeEvaluator()
    result = evaluator.evaluate(sample_code)
    print(json.dumps(result, indent=2))
