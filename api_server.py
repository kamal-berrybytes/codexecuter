#!/usr/bin/env python3
"""
REST API Server for Gvisor Code Execution Platform

This module provides a Flask-based REST API with an embedded Web UI
for submitting Python code for execution in Gvisor-sandboxed
Kubernetes pods.

Usage:
    python api_server.py

Endpoints:
    GET  /                  - Web UI interface
    POST /api/execute       - Submit code for execution
    GET  /api/status/<id>   - Get execution status
    GET  /api/results       - List all execution results

Environment:
    PORT: Server port (default: 5000)
    KUBERNETES_MODE: Always 'true' for K8s-driven execution
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Dict, Any

from flask import Flask, request, jsonify, render_template_string

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

os.environ["KUBERNETES_MODE"] = "true"

app = Flask(__name__)

RESULTS_STORE: Dict[str, Dict[str, Any]] = {}

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Gvisor Code Execution</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f7fa; }
        h1 { color: #2c3e50; margin-bottom: 20px; }
        h2 { color: #34495e; margin-bottom: 15px; }
        .card { background: white; padding: 20px; border-radius: 8px; 
                margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        label { display: block; margin-bottom: 8px; font-weight: 600; color: #555; }
        input, select, textarea { width: 100%; padding: 12px; margin-bottom: 15px; 
                                   border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
        textarea { font-family: 'Monaco', 'Menlo', monospace; min-height: 120px; }
        button { background: #3498db; color: white; padding: 12px 24px; 
                 border: none; border-radius: 6px; cursor: pointer; font-size: 14px; 
                 font-weight: 600; transition: background 0.2s; }
        button:hover { background: #2980b9; }
        button:disabled { background: #95a5a6; cursor: not-allowed; }
        .result { background: #ecf0f1; padding: 15px; border-radius: 6px; margin-top: 15px; }
        .result.success { border-left: 4px solid #27ae60; }
        .result.error { border-left: 4px solid #e74c3c; }
        .result.warning { border-left: 4px solid #f39c12; }
        pre { background: #2c3e50; color: #ecf0f1; padding: 15px; border-radius: 6px; 
              overflow-x: auto; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #34495e; color: white; font-weight: 600; }
        tr:hover { background: #f8f9fa; }
        .status { padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
        .status-pending { background: #f39c12; color: white; }
        .status-running { background: #3498db; color: white; }
        .status-completed { background: #27ae60; color: white; }
        .status-failed { background: #e74c3c; color: white; }
        .loading { text-align: center; padding: 20px; color: #7f8c8d; }
        .test-results { margin-top: 10px; }
        .test-item { padding: 8px 12px; margin: 5px 0; border-radius: 4px; font-size: 13px; }
        .test-passed { background: #d4edda; border-left: 3px solid #28a745; }
        .test-failed { background: #f8d7da; border-left: 3px solid #dc3545; }
        .test-status { font-weight: bold; margin-right: 5px; }
        .semgrep-results { margin-top: 10px; }
        .semgrep-finding { background: #fff3cd; padding: 8px; margin: 5px 0; border-radius: 4px; font-size: 12px; border-left: 3px solid #ffc107; }
    </style>
</head>
<body>
    <h1>Gvisor Code Execution Platform</h1>
    
    <div class="card">
        <h2>Execute Code</h2>
        <form id="executeForm">
            <label>Execution Mode:</label>
            <select id="mode" name="mode">
                <option value="task">LLM Task (describe what you want)</option>
                <option value="prompt">LLM Prompt (custom instructions)</option>
                <option value="code">Direct Python Code</option>
            </select>
            
            <label id="inputLabel">Task Description:</label>
            <input type="text" id="taskInput" placeholder="e.g., reverse a string, calculate fibonacci">
            
            <button type="submit" id="submitBtn">Execute in Gvisor Sandbox</button>
        </form>
        <div id="result"></div>
    </div>
    
    <div class="card">
        <h2>Execution History</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Mode</th>
                    <th>Input</th>
                    <th>Status</th>
                    <th>Tests</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody id="historyTable">
                <tr><td colspan="6" class="loading">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        const modeSelect = document.getElementById('mode');
        const inputLabel = document.getElementById('inputLabel');
        const taskInput = document.getElementById('taskInput');
        const submitBtn = document.getElementById('submitBtn');

        modeSelect.addEventListener('change', function() {
            if (this.value === 'code') {
                inputLabel.textContent = 'Python Code:';
                taskInput.placeholder = 'def reverse_string(s):\\n    return s[::-1]';
                taskInput.removeAttribute('type');
                taskInput.tagName === 'INPUT' ? taskInput.outerHTML = '<textarea id="taskInput" placeholder="def reverse_string(s):\\n    return s[::-1]"></textarea>' : null;
            } else if (this.value === 'task') {
                inputLabel.textContent = 'Task Description:';
                taskInput.outerHTML = '<input type="text" id="taskInput" placeholder="e.g., reverse a string">';
            } else {
                inputLabel.textContent = 'LLM Prompt:';
                taskInput.outerHTML = '<input type="text" id="taskInput" placeholder="Generate a function that...">';
            }
        });

        function loadHistory() {
            fetch('/api/results')
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById('historyTable');
                    if (!data.results || data.results.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" class="loading">No executions yet</td></tr>';
                        return;
                    }
                    tbody.innerHTML = data.results.reverse().map(r => {
                        const statusClass = 'status-' + (r.status || 'pending');
                        const tests = r.evaluation ? r.evaluation.passed_tests + '/' + r.evaluation.total_tests : '-';
                        const input = (r.input || '').substring(0, 25) + ((r.input || '').length > 25 ? '...' : '');
                        return '<tr><td>' + (r.job_id || '').substring(0,8) + 
                               '</td><td>' + (r.mode || '-') + 
                               '</td><td>' + input + 
                               '</td><td><span class="status ' + statusClass + '">' + (r.status || 'pending') + 
                               '</span></td><td>' + tests + 
                               '</td><td>' + new Date(r.timestamp).toLocaleTimeString() + '</td></tr>';
                    }).join('');
                });
        }

        document.getElementById('executeForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const mode = document.getElementById('mode').value;
            const inputEl = document.getElementById('taskInput');
            const input = inputEl.tagName === 'TEXTAREA' ? inputEl.value : inputEl.value;
            
            submitBtn.disabled = true;
            submitBtn.textContent = 'Executing...';
            document.getElementById('result').innerHTML = '<div class="result">Processing request...</div>';
            
            fetch('/api/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: mode, input: input})
            })
            .then(r => r.json())
            .then(data => {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Execute in Gvisor Sandbox';
                
                if (data.job_id) {
                    document.getElementById('result').innerHTML = '<div class="result success"><p><strong>Job ID:</strong> ' + data.job_id + '</p><p><strong>Status:</strong> ' + data.status + '</p></div>';
                    checkStatus(data.job_id);
                } else {
                    document.getElementById('result').innerHTML = '<div class="result error"><p>Error: ' + (data.error || 'Unknown error') + '</p></div>';
                }
            })
            .catch(err => {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Execute in Gvisor Sandbox';
                document.getElementById('result').innerHTML = '<div class="result error"><p>Network error</p></div>';
            });
            
            setTimeout(loadHistory, 1000);
        });

        function checkStatus(jobId) {
            fetch('/api/status/' + jobId)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'completed' || data.status === 'failed') {
                        const resultDiv = document.getElementById('result');
                        let html = '<div class="result ';
                        html += data.status === 'completed' ? 'success' : 'error';
                        html += '"><p><strong>Status:</strong> ' + data.status + '</p>';
                        if (data.security) {
                            html += '<p><strong>Security:</strong> ' + (data.security.safe ? 'Safe' : 'Unsafe') + '</p>';
                        }
                        if (data.execution) {
                            html += '<p><strong>Execution:</strong> ' + (data.execution.success ? 'Success' : 'Failed') + '</p>';
                        }
                        if (data.evaluation) {
                            html += '<p><strong>Tests:</strong> ' + data.evaluation.passed_tests + '/' + data.evaluation.total_tests + ' passed</p>';
                            html += '<div class="test-results">';
                            if (data.evaluation.test_results) {
                                data.evaluation.test_results.forEach(test => {
                                    const statusIcon = test.passed ? '✓' : '✗';
                                    const statusClass = test.passed ? 'test-passed' : 'test-failed';
                                    html += '<div class="test-item ' + statusClass + '">';
                                    html += '<span class="test-status">' + statusIcon + '</span> ';
                                    html += '<strong>' + test.name + '</strong>';
                                    if (test.input !== null && test.input !== undefined) {
                                        html += ' | Input: ' + JSON.stringify(test.input);
                                    }
                                    if (test.expected !== null && test.expected !== undefined) {
                                        html += ' | Expected: ' + JSON.stringify(test.expected);
                                    }
                                    if (test.actual !== null && test.actual !== undefined) {
                                        html += ' | Actual: ' + JSON.stringify(test.actual);
                                    }
                                    if (test.error) {
                                        html += ' | Error: ' + test.error;
                                    }
                                    html += '</div>';
                                });
                            }
                            html += '</div>';
                            
                            if (data.evaluation.semgrep_analysis) {
                                const sr = data.evaluation.semgrep_analysis;
                                html += '<p><strong>Semgrep Analysis:</strong> ' + sr.findings_count + ' findings</p>';
                                if (sr.findings && sr.findings.length > 0) {
                                    html += '<div class="semgrep-results">';
                                    sr.findings.forEach(f => {
                                        html += '<div class="semgrep-finding">';
                                        html += '<strong>[' + f.severity + ']</strong> ' + f.rule_id + ': ' + f.message;
                                        html += '</div>';
                                    });
                                    html += '</div>';
                                }
                            }
                        }
                        html += '</div>';
                        resultDiv.innerHTML = html;
                    } else if (data.status === 'running') {
                        setTimeout(() => checkStatus(jobId), 2000);
                    }
                });
        }

        loadHistory();
        setInterval(loadHistory, 5000);
    </script>
</body>
</html>"""


@app.route("/")
def index():
    """Render the Web UI."""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/execute", methods=["POST"])
def execute():
    """
    Execute code through the full pipeline: security analysis,
    sandbox execution, and evaluation.

    Request JSON:
        {
            "mode": "task|prompt|code",
            "input": "string"
        }

    Returns:
        {"job_id": "uuid", "status": "..."}
    """
    data = request.json or {}
    mode = data.get("mode", "code")
    user_input = data.get("input", "")

    job_id = str(uuid.uuid4())

    RESULTS_STORE[job_id] = {
        "job_id": job_id,
        "mode": mode,
        "input": user_input,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "security": None,
        "execution": None,
        "evaluation": None,
    }

    try:
        from agent.langchain_agent import CodeGenerationAgent

        agent = CodeGenerationAgent()
        code = None

        if mode == "code":
            code = user_input
        elif mode == "task":
            code = agent.generate_code_from_task(user_input)
        elif mode == "prompt":
            code = agent.generate_code(user_input)
        else:
            raise ValueError(f"Invalid mode: {mode}")

        if code is None:
            raise ValueError("No code generated")

        RESULTS_STORE[job_id]["status"] = "running"
        RESULTS_STORE[job_id]["generated_code"] = code

        logger.info(f"Job {job_id}: Running security analysis")
        from security.security_analyzer import SecurityAnalyzer

        analyzer = SecurityAnalyzer()
        is_safe, report = analyzer.analyze(code)

        RESULTS_STORE[job_id]["security"] = {"safe": is_safe, "report": report}

        if not is_safe:
            RESULTS_STORE[job_id]["status"] = "failed"
            return jsonify(
                {"job_id": job_id, "status": "failed", "error": "Security check failed"}
            )

        logger.info(f"Job {job_id}: Executing in Gvisor sandbox")
        from sandbox.gvisor_executor import GvisorSandboxExecutor

        executor = GvisorSandboxExecutor()
        exec_result = executor.execute(code)  

        RESULTS_STORE[job_id]["execution"] = exec_result

        if not exec_result["success"]:
            RESULTS_STORE[job_id]["status"] = "failed"
            return jsonify(
                {"job_id": job_id, "status": "failed", "error": "Execution failed"}
            )

        logger.info(f"Job {job_id}: Evaluating code")
        from evaluation.evaluator import CodeEvaluator

        evaluator = CodeEvaluator(output_dir=executor.output_dir)
        eval_result = evaluator.evaluate(code, exec_result.get("output"))

        RESULTS_STORE[job_id]["evaluation"] = eval_result
        RESULTS_STORE[job_id]["status"] = "completed"

        return jsonify(
            {"job_id": job_id, "status": "completed", "evaluation": eval_result}
        )

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        RESULTS_STORE[job_id]["status"] = "failed"
        RESULTS_STORE[job_id]["error"] = str(e)
        return jsonify({"job_id": job_id, "status": "failed", "error": str(e)})


@app.route("/api/status/<job_id>", methods=["GET"])
def get_status(job_id: str):
    """Get the status of a specific execution."""
    result = RESULTS_STORE.get(job_id)
    if not result:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(result)


@app.route("/api/results", methods=["GET"])
def list_results():
    """List all execution results."""
    return jsonify({"results": list(RESULTS_STORE.values())})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
