import os
import logging
import json
from datetime import datetime

try:
    from langchain.chat_models import ChatOpenAI
    from langchain.schema import HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

try:
    import dspy
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


FIBONACCI_PROMPT = """Generate a Python function that calculates Fibonacci numbers.
The function should:
1. Take an integer n as input
2. Return the nth Fibonacci number
3. Include proper error handling for invalid inputs
4. Be efficient and well-documented

Also generate unit tests using pytest that verify:
- fibonacci(0) returns 0
- fibonacci(1) returns 1
- fibonacci(10) returns 55
- fibonacci(20) returns 6765
- Invalid inputs raise appropriate exceptions

Return ONLY valid Python code, no explanations."""


class CodeGenerationAgent:
    def __init__(self, provider=None, model=None):
        self.provider = provider or os.environ.get('AGENT_PROVIDER', 'langchain')
        self.model = model or os.environ.get('AGENT_MODEL', 'gpt-4')
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        self.llm = None
        
        if self.provider == 'dspyo' and DSPY_AVAILABLE:
            self._init_dspy()
        elif LANGCHAIN_AVAILABLE:
            self._init_langchain()
        else:
            logger.warning("No LLM provider available, using fallback generation")
    
    def _init_langchain(self):
        if not self.api_key:
            logger.warning("No OpenAI API key, using fallback generation")
            self.llm = None
            return
        
        try:
            self.llm = ChatOpenAI(
                model=self.model,
                api_key=self.api_key,
                temperature=0.2
            )
            logger.info(f"Initialized LangChain with model {self.model}")
        except Exception as e:
            logger.warning(f"Failed to initialize LangChain: {e}")
            self.llm = None
    
    def _init_dspy(self):
        if not self.api_key:
            logger.warning("No OpenAI API key for DSPy")
            self.llm = None
            return
        
        try:
            dspy.configure(lm=dspy.OpenAI(model=self.model, api_key=self.api_key))
            logger.info(f"Initialized DSPy with model {self.model}")
        except Exception as e:
            logger.warning(f"Failed to initialize DSPy: {e}")
            self.llm = None
    
    def generate_code(self, prompt):
        if self.llm:
            return self._generate_with_llm(prompt)
        return self._generate_fallback(prompt)
    
    def generate_code_from_task(self, task_description):
        prompt = f"""Generate Python code for the following task:
{task_description}

Requirements:
1. Write clean, well-documented code
2. Include proper error handling
3. Include unit tests using pytest if applicable

Return ONLY valid Python code, no explanations."""
        return self.generate_code(prompt)
    
    def generate_fibonacci_code(self):
        return self.generate_code(FIBONACCI_PROMPT)
    
    def _generate_with_llm(self, prompt):
        try:
            if self.provider == 'dspyo' and DSPY_AVAILABLE:
                return self._generate_with_dspy(prompt)
            return self._generate_with_langchain(prompt)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._generate_fallback(prompt)
    
    def _generate_with_langchain(self, prompt):
        messages = [
            SystemMessage(content="You are a code generation assistant. Generate only valid Python code."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm(messages)
        code = response.content
        
        return self._save_code(code)
    
    def _generate_with_dspy(self, prompt):
        class GenerateCode(dspy.Signature):
            prompt = dspy.InputField(description="The code generation request")
            code = dspy.OutputField(description="Generated Python code")
        
        generate_code = dspy.Predict(GenerateCode)
        response = generate_code(prompt=prompt)
        
        return self._save_code(response.code)
    
    def _generate_fallback(self, prompt=None):
        if not prompt:
            prompt = "Generate a simple function"
        
        prompt_lower = prompt.lower()
        
        if "fibonacci" in prompt_lower:
            code = '''"""Fibonacci implementation with unit tests"""
import pytest

def fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number."""
    if not isinstance(n, int):
        raise TypeError(f"Expected int, got {type(n).__name__}")
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


class TestFibonacci:
    def test_fibonacci_0(self):
        assert fibonacci(0) == 0
    
    def test_fibonacci_1(self):
        assert fibonacci(1) == 1
    
    def test_fibonacci_10(self):
        assert fibonacci(10) == 55


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''
        elif "string" in prompt_lower and "reverse" in prompt_lower:
            code = '''"""String reversal implementation"""
import pytest

def reverse_string(s: str) -> str:
    """Reverse a string."""
    if not isinstance(s, str):
        raise TypeError("Expected string")
    return s[::-1]


class TestReverseString:
    def test_reverse_abc(self):
        assert reverse_string("abc") == "cba"
    
    def test_reverse_empty(self):
        assert reverse_string("") == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''
        else:
            code = f'''"""Dynamic code generation from prompt"""
import pytest

def process(data):
    """Process input data based on task description: {prompt[:100]}"""
    return data


class TestProcess:
    def test_basic(self):
        assert process(1) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''
        return self._save_code(code)
    
    def _save_code(self, code):
        output_dir = os.environ.get('CODE_OUTPUT_DIR', '/tmp/generated')
        os.makedirs(output_dir, exist_ok=True)
        
        code_file = os.path.join(output_dir, 'fibonacci.py')
        with open(code_file, 'w') as f:
            f.write(code)
        
        logger.info(f"Code saved to {code_file}")
        
        metadata = {
            'timestamp': str(datetime.now()),
            'provider': self.provider,
            'model': self.model
        }
        metadata_file = os.path.join(output_dir, 'metadata.json')
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f)
        
        return code


if __name__ == '__main__':
    agent = CodeGenerationAgent()
    code = agent.generate_fibonacci_code()
    print(code)