# Sequence Diagram - Gvisor Code Execution Platform

```mermaid
sequenceDiagram
    participant User as Browser/User
    participant API as API Server (Flask)
    participant Agent as CodeGenerationAgent
    participant Security as SecurityAnalyzer
    participant Sandbox as GvisorSandboxExecutor
    participant K8s as Kubernetes API
    participant Pod1 as Sandbox Pod (gvisor)
    participant Evaluator as CodeEvaluator
    participant Pod2 as Semgrep Pod (gvisor)

    User->>API: POST /api/execute {mode, input}
    API->>API: Generate job_id
    API->>API: Store job in RESULTS_STORE

    alt mode == "task" or mode == "prompt"
        API->>Agent: generate_code(input)
        Agent-->>API: Generated Python code
    else mode == "code"
        API->>API: Use user_input as code
    end

    API->>Security: SecurityAnalyzer.analyze(code)
    Security-->>API: (is_safe, report)

    alt is_safe == false
        API-->>User: Return error: Security check failed
    else is_safe == true
        API->>Sandbox: GvisorSandboxExecutor.execute(code)
        
        Sandbox->>Sandbox: _save_code(code) → /tmp/code/code.py
        Sandbox->>Sandbox: _generate_pod_spec()
        Sandbox->>K8s: kubectl apply -f sandbox-pod.yaml
        K8s->>Pod1: Create Pod (runtimeClassName: gvisor)
        
        Pod1->>Pod1: python /tmp/code/code.py
        Pod1-->>K8s: Pod completes (Succeeded/Failed)
        K8s-->>Sandbox: Return pod status & logs
        Sandbox-->>API: {success, output, error}
        
        API->>Evaluator: CodeEvaluator.evaluate(code, output)
        
        Evaluator->>Evaluator: _auto_generate_tests(code)
        Evaluator->>Evaluator: Run tests against code
        
        Evaluator->>Evaluator: _run_semgrep(code)
        Evaluator->>Evaluator: Save code to /tmp/code/code.py
        Evaluator->>K8s: kubectl apply -f semgrep-pod.yaml
        K8s->>Pod2: Create Semgrep Pod
        
        Pod2->>Pod2: Install semgrep → semgrep scan
        Pod2-->>K8s: Pod completes
        K8s-->>Evaluator: Return semgrep results
        Evaluator-->>API: {passed, test_results, semgrep_analysis}
        
        API->>API: Update RESULTS_STORE with results
        API-->>User: {job_id, status, evaluation}
    end

    Note over User,API: Results displayed in Web UI
```

## Detailed Flow Description

### 1. Request Submission
- User submits code via web interface at `/api/execute`
- Supports 3 modes: `code` (direct), `task` (LLM task), `prompt` (LLM prompt)

### 2. Code Generation (if needed)
- For `task`/`prompt` modes: `CodeGenerationAgent` generates Python code
- For `code` mode: Uses user-provided code directly

### 3. Security Analysis
- `SecurityAnalyzer.analyze(code)` checks for dangerous patterns
- Blocked patterns: subprocess, os.system, eval, exec, socket, file operations, etc.
- If unsafe: Returns error immediately

### 4. Sandbox Execution
- Code saved to `/tmp/code/code.py` on shared PVC
- Creates Kubernetes pod with `runtimeClassName: gvisor`
- Pod executes: `python /tmp/code/code.py`
- Returns execution output

### 5. Code Evaluation
- Auto-generates test cases based on function names
- Runs tests against the code
- Creates separate Semgrep analyzer pod
- Semgrep scans for security vulnerabilities

### 6. Results Return
- All results stored in `RESULTS_STORE`
- Response includes: job_id, status, test results, semgrep findings
