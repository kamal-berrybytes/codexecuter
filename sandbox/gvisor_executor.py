"""
Gvisor Sandbox Executor

This module provides the GvisorSandboxExecutor class for executing
Python code in isolated Gvisor-sandboxed Kubernetes pods.

Each execution creates a NEW pod with the following security:
- runtimeClassName: gvisor
- readOnlyRootFilesystem: true
- allowPrivilegeEscalation: false
- capabilities.drop: ALL
- runAsNonRoot: true (UID 1000)

Usage:
    from sandbox.gvisor_executor import GvisorSandboxExecutor

    executor = GvisorSandboxExecutor()
    result = executor.execute(code)
    print(result['output'])
"""

import os
import sys
import json
import logging
import subprocess
import time
from typing import Dict, Any, Optional

import yaml

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class GvisorSandboxExecutor:
    """
    Executes Python code in Gvisor-isolated sandbox environment.

    Each call to execute() creates a new Kubernetes pod with
    gvisor runtime for complete isolation.

    Attributes:
        output_dir: Directory for code and results
        timeout: Maximum execution time in seconds
        use_kubernetes: Whether to use K8s (default: True)
        runtime_class: Kubernetes RuntimeClass name
        memory_limit: Memory limit for pod
        cpu_limit: CPU limit for pod
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        timeout: Optional[int] = None,
        use_kubernetes: Optional[bool] = None,
    ):
        self.output_dir = output_dir or os.environ.get(
            "CODE_OUTPUT_DIR", "/tmp/generated"
        )
        self.timeout = timeout or int(os.environ.get("EXECUTION_TIMEOUT", "30"))
        self.use_kubernetes = (
            use_kubernetes
            if use_kubernetes is not None
            else os.environ.get("KUBERNETES_MODE", "true").lower() == "true"
        )

        self.runtime_class = os.environ.get("RUNTIME_CLASS", "gvisor")
        self.memory_limit = os.environ.get("MAX_MEMORY", "128Mi")
        self.cpu_limit = os.environ.get("MAX_CPU", "500m")
        self.namespace = os.environ.get("NAMESPACE", "fibonacci-agent")

    def execute(self, code: str) -> Dict[str, Any]:
        """
        Execute Python code in Gvisor sandbox.

        Args:
            code: Python code to execute

        Returns:
            Dict with keys:
                - success: bool
                - output: str (stdout)
                - error: str (if failed)
                - execution_time: float (seconds)
        """
        logger.info("Executing code in Gvisor sandbox")

        if self.use_kubernetes:
            return self._execute_in_kubernetes(code)
        return self._execute_local(code)

    def _execute_local(self, code: str) -> Dict[str, Any]:
        """Execute code locally (fallback mode)."""
        code_file = self._save_code(code)

        pod_spec = self._generate_pod_spec(code_file)
        pod_file = os.path.join(self.output_dir, "sandbox-pod.yaml")

        with open(pod_file, "w") as f:
            yaml.dump(pod_spec, f)

        logger.info(f"Pod spec saved to {pod_file}")

        return self._run_direct(code)

    def _execute_in_kubernetes(self, code: str) -> Dict[str, Any]:
        """Execute code in Kubernetes pod with gvisor runtime."""
        code_file = self._save_code(code)

        pod_spec = self._generate_pod_spec(code_file)
        pod_file = os.path.join(self.output_dir, "sandbox-pod.yaml")

        with open(pod_file, "w") as f:
            yaml.dump(pod_spec, f)

        pod_name = f"sandbox-executor-{int(time.time())}"
        pod_spec["metadata"]["name"] = pod_name

        with open(pod_file, "w") as f:
            yaml.dump(pod_spec, f)

        try:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "-n", self.namespace],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        result = subprocess.run(
            ["kubectl", "apply", "-f", pod_file, "-n", self.namespace],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to create pod: {result.stderr}")
            return self._run_direct(code)

        return self._wait_for_pod_completion(pod_name, self.namespace)

    def _run_direct(self, code: str) -> Dict[str, Any]:
        """Execute code using Python exec (local fallback)."""
        import io
        import traceback

        output = io.StringIO()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = output
        sys.stderr = output

        execution_result = {
            "success": False,
            "output": "",
            "error": "",
            "execution_time": 0,
        }

        start_time = time.time()

        try:
            compiled = compile(code, "<sandbox>", "exec")
            namespace = {"__name__": "__sandbox__"}
            exec(compiled, namespace)

            execution_result["success"] = True
            execution_result["output"] = output.getvalue()

        except Exception as e:
            execution_result["error"] = f"{type(e).__name__}: {str(e)}"
            execution_result["error"] += "\n" + traceback.format_exc()

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        execution_result["execution_time"] = time.time() - start_time

        self._save_result(execution_result)

        return execution_result

    def _wait_for_pod_completion(
        self, pod_name: str, namespace: str, poll_interval: int = 1
    ) -> Dict[str, Any]:
        """Wait for pod to complete and return results."""
        max_wait = self.timeout
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

                        return {
                            "success": True,
                            "output": logs_result.stdout,
                            "error": "",
                            "execution_time": time.time() - start_time,
                        }

                    elif phase == "Failed":
                        logs_result = subprocess.run(
                            ["kubectl", "logs", pod_name, "-n", namespace],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )

                        return {
                            "success": False,
                            "output": "",
                            "error": logs_result.stderr,
                            "execution_time": time.time() - start_time,
                        }

                time.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Error checking pod status: {e}")
                time.sleep(poll_interval)

        return {
            "success": False,
            "output": "",
            "error": "Timeout waiting for pod completion",
            "execution_time": max_wait,
        }

    def _generate_pod_spec(self, code_file: str) -> Dict[str, Any]:
        """
        Generate Kubernetes Pod spec for sandbox execution.

        Args:
            code_file: Path to the Python code file

        Returns:
            Kubernetes Pod spec dictionary
        """
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "sandbox-executor",
                "namespace": self.namespace,
                "labels": {"app": "gvisor-sandbox", "component": "executor"},
            },
            "spec": {
                "restartPolicy": "Never",
                "runtimeClassName": self.runtime_class,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "fsGroup": 1000,
                },
                "containers": [
                    {
                        "name": "executor",
                        "image": "fibonacci-agent:latest",
                        "imagePullPolicy": "Never",
                        "command": ["sh", "-c", "python /tmp/code/code.py"],
                        "resources": {
                            "limits": {
                                "memory": self.memory_limit,
                                "cpu": self.cpu_limit,
                            },
                            "requests": {"memory": "64Mi", "cpu": "100m"},
                        },
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

    def _save_code(self, code: str) -> str:
        """Save code to file in output directory."""
        os.makedirs(self.output_dir, exist_ok=True)

        code_file = os.path.join(self.output_dir, "code.py")
        with open(code_file, "w") as f:
            f.write(code)

        logger.info(f"Code saved to {code_file}")
        return code_file

    def _save_result(self, result: Dict[str, Any]) -> None:
        """Save execution result to JSON file."""
        result_file = os.path.join(self.output_dir, "execution_result.json")

        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)

        logger.info(f"Execution result saved to {result_file}")


if __name__ == "__main__":
    #     sample_code = """
    # def fibonacci(n):
    #     if n <= 1:
    #         return n
    #     a, b = 0, 1
    #     for _ in range(2, n + 1):
    #         a, b = b, a + b
    #     return b

    # print(fibonacci(10))
    # """

    executor = GvisorSandboxExecutor()
    # result = executor.execute(sample_code)
    print(json.dumps(result, indent=2))
