# Gvisor Code Execution Platform - Technical Documentation

## Overview

This platform provides a REST API for executing Python code in isolated Gvisor-sandboxed Kubernetes pods with integrated security scanning using Semgrep.

## Architecture

```
User UI (Browser)
    │
    ▼
┌─────────────────────────────┐
│   API Server (Flask)         │
│   (Kubernetes Pod)           │
│   Port: 5000                 │
└─────────────────────────────┘
    │
    ├──▶ Security Analysis
    │       │
    │       ▼
    │       Security Analyzer
    │
    ├──▶ Sandbox Execution
    │       │
    │       ▼
    │       Gvisor Sandbox Pod
    │       - runtimeClassName: gvisor
    │       - Mounts PVC at /tmp/code
    │
    └──▶ Code Evaluation + Semgrep
            │
            ▼
            Semgrep Analyzer Pod
            - Runs semgrep scan
            - Scans same PVC location
```

## Code Flow

### 1. User Input (UI)
- User submits Python code via web interface
- Three modes: `code` (direct), `task` (LLM task), `prompt` (LLM prompt)
- Code sent as JSON to `/api/execute` endpoint

### 2. API Server (api_server.py)
- Receives code from UI
- Generates code (if using LLM modes)
- Runs security analysis
- Executes code in sandbox
- Evaluates with Semgrep

**Key Code:**
```python
# api_server.py - Lines 324-371
if mode == "code":
    code = user_input
# ... security check ...
executor = GvisorSandboxExecutor()
exec_result = executor.execute(code)
evaluator = CodeEvaluator(output_dir=executor.output_dir)
eval_result = evaluator.evaluate(code, exec_result.get("output"))
```

### 3. Sandbox Execution (sandbox/gvisor_executor.py)
- Saves code to PVC-mounted directory
- Creates Kubernetes pod with Gvisor runtime
- Executes the Python code
- Returns output

**Code Location:**
```python
# sandbox/gvisor_executor.py
self.output_dir = "/tmp/code"  # From CODE_OUTPUT_DIR env
code_file = os.path.join(self.output_dir, "code.py")
# Result: /tmp/code/code.py
```

### 4. Semgrep Evaluation (evaluation/evaluator.py)
- Writes same code to same PVC location
- Creates separate analyzer pod
- Runs `semgrep scan` on the code
- Returns security findings

**Semgrep Command:**
```python
# evaluation/evaluator.py - Pod command
"python -m venv /tmp/venv && /tmp/venv/bin/pip install semgrep && \
cp /tmp/code/code.py /tmp/code/target.py && cd /tmp/code && \
/tmp/venv/bin/semgrep scan --json --verbose ... --config auto target.py"
```

## File Structure

```
/home/kamal/Desktop/gvisortest/
├── api_server.py           # Flask REST API server
├── sandbox/
│   └── gvisor_executor.py # Gvisor sandbox executor
├── evaluation/
│   └── evaluator.py       # Code evaluation + Semgrep
├── security/
│   └── security_analyzer.py # Security analysis
├── agent/
│   └── langchain_agent.py # LLM code generation
├── kubernetes/
│   ├── api-deployment.yaml    # API server deployment
│   ├── agent-deployment.yaml  # Agent deployment
│   └── *.yaml                 # Other K8s configs
├── Dockerfile                # Container image
└── README.md
```

## Kubernetes Deployment

### API Server Deployment

```yaml
# kubernetes/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: code-executor-api
  namespace: fibonacci-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: code-executor-api
  template:
    spec:
      serviceAccountName: fibonacci-agent-sa
      containers:
        - name: api
          image: fibonacci-agent:latest
          imagePullPolicy: Never
          command: ["python", "/app/api_server.py"]
          env:
            - name: KUBERNETES_MODE
              value: "true"
            - name: CODE_OUTPUT_DIR
              value: "/tmp/code"
            - name: PORT
              value: "5000"
          volumeMounts:
            - name: code-volume
              mountPath: /tmp/code
      volumes:
        - name: code-volume
          persistentVolumeClaim:
            claimName: generated-code-pvc
```

### Persistent Volume Claim

The system uses a PVC (`generated-code-pvc`) to share code between:
1. API Server (writes code)
2. Sandbox Executor Pod (reads & executes)
3. Semgrep Analyzer Pod (reads & scans)

**Mount Path:** `/tmp/code/`  
**Code File:** `/tmp/code/code.py`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 5000 | API server port |
| `KUBERNETES_MODE` | true | Enable K8s execution |
| `CODE_OUTPUT_DIR` | /tmp/code | Code storage directory |
| `EXECUTION_TIMEOUT` | 30 | Max execution time (seconds) |
| `RUNTIME_CLASS` | gvisor | Kubernetes runtime class |
| `NAMESPACE` | fibonacci-agent | Kubernetes namespace |
| `MAX_MEMORY` | 128Mi | Pod memory limit |
| `MAX_CPU` | 500m | Pod CPU limit |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI interface |
| `/api/execute` | POST | Submit code for execution |
| `/api/status/<job_id>` | GET | Get execution status |
| `/api/results` | GET | List all results |

### Execute Request

```json
POST /api/execute
{
  "mode": "code",      // "code", "task", or "prompt"
  "input": "def add(a,b):\n    return a + b"
}
```

### Execute Response

```json
{
  "job_id": "uuid",
  "status": "completed",
  "evaluation": {
    "passed": true,
    "total_tests": 3,
    "passed_tests": 3,
    "failed_tests": 0,
    "test_results": [...],
    "semgrep_analysis": {
      "success": true,
      "findings": [...],
      "findings_count": 0
    }
  }
}
```

## Security Features

### 1. Pre-Execution Security Analysis (security_analyzer.py)

Before any code is sent to the sandbox, it undergoes security analysis in `security/security_analyzer.py`:

**How it works:**
- Code is analyzed before execution using pattern matching
- If dangerous patterns are found, execution is blocked immediately
- Returns `(is_safe, report)` tuple

**Dangerous Patterns Checked:**

| Category | Patterns Blocked |
|----------|------------------|
| **Execution** | `subprocess.run`, `subprocess.Popen`, `os.system`, `eval`, `exec`, `compile` |
| **Network** | `socket`, `urllib`, `requests`, `http` module |
| **Filesystem** | `os.chmod`, `os.chown`, `os.remove`, `os.unlink`, `shutil.rmtree`, file write/append |
| **Code Loading** | `__import__`, `pickle.load`, `yaml.load`, `marshal.load` |
| **Runtime** | `globals`, `locals`, `vars`, dynamic modules |

**Allowed Imports:**
```
math, random, datetime, time, json, re, functools, itertools, 
collections, operator, typing, sys, os.path, pytest, unittest, 
abc, copy, bisect, array
```

**Code Location:** `security/security_analyzer.py` (Lines 36-65)

```python
# security/security_analyzer.py
DANGEROUS_PATTERNS = [
    (r'subprocess\.(run|Popen|call|check_output)', 'subprocess execution'),
    (r'os\.system\s*\(', 'os.system call'),
    (r'eval\s*\(', 'eval function'),
    (r'exec\s*\(', 'exec function'),
    # ... more patterns
]

# Usage in api_server.py:
analyzer = SecurityAnalyzer()
is_safe, report = analyzer.analyze(code)
if not is_safe:
    return jsonify({"status": "failed", "error": "Security check failed"})
```

**Flow:**
```
User Code → SecurityAnalyzer.analyze() → 
    ├── Safe → Continue to Sandbox
    └── Unsafe → Block execution, return error
```

### 2. Gvisor Isolation

- Uses gvisor runtime for sandboxing
- `runtimeClassName: gvisor`
- `readOnlyRootFilesystem: false` (needed for venv)
- `allowPrivilegeEscalation: false`
- `capabilities.drop: ALL`
- Runs as non-root user (UID 1000)

### 3. Semgrep Security Scanning

- Runs in separate Kubernetes pod after execution
- Uses `--config auto` for automatic rule selection
- Scans for security vulnerabilities, code quality issues
- Results displayed in UI

## Deployment Steps

1. **Build Docker Image:**
   ```bash
   docker build -t fibonacci-agent:latest .
   ```

2. **Load into Kind (if applicable):**
   ```bash
   kind load docker-image fibonacci-agent:latest
   ```

3. **Apply Kubernetes Configs:**
   ```bash
   kubectl apply -f kubernetes/api-deployment.yaml
   ```

4. **Restart API Pod:**
   ```bash
   kubectl rollout restart deployment/code-executor-api -n fibonacci-agent
   ```

5. **Check Status:**
   ```bash
   kubectl get pods -n fibonacci-agent
   kubectl logs -n fibonacci-agent -l app=code-executor-api
   ```

## Pod Creation Flow

### 1. Sandbox Executor Pod
- **Image:** fibonacci-agent:latest
- **Command:** `python /tmp/code/code.py`
- **Runtime:** gvisor
- **Mounts:** PVC at `/tmp/code`

### 2. Semgrep Analyzer Pod
- **Image:** fibonacci-agent:latest
- **Command:** Creates venv, installs semgrep, runs scan
- **Runtime:** gvisor
- **Mounts:** Same PVC at `/tmp/code`

## Troubleshooting

### Check Pod Logs
```bash
kubectl logs <pod-name> -n fibonacci-agent
```

### Check Pod Events
```bash
kubectl describe pod <pod-name> -n fibonacci-agent
```

### Verify PVC Mount
```bash
kubectl exec -it <pod-name> -n fibonacci-agent -- ls -la /tmp/code
```

### View Semgrep Results
```bash
kubectl logs <semgrep-analyzer-pod> -n fibonacci-agent
```
