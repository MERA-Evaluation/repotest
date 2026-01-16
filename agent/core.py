import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from openai import OpenAI


class BashAgent:
    def __init__(self, token: str, config_path: str = "configs/jest_config.json"):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=token
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.trajectory: List[Dict[str, Any]] = []
        self.max_iterations = self.config.get('max_iterations', 5)
        self.model = self.config.get('model', 'qwen/qwen3-next-80b-a3b-instruct')
        
    def _log_step(self, step_type: str, data: Dict[str, Any]):
        step = {
            'timestamp': datetime.now().isoformat(),
            'step_type': step_type,
            'data': data
        }
        print(json.dumps(step, ensure_ascii=False))
        self.trajectory.append(step)
    
    def _read_repo_files(self, repo) -> Dict[str, str]:
        file_patterns = [
            "package.json",
            "jest.config.js",
            "jest.config.json",
            ".babelrc",
            "babel.config.js",
            "tsconfig.json",
            "webpack.config.js"
        ]
        
        files_content = {}
        
        try:
            if hasattr(repo, 'run_command'):
                for pattern in file_patterns:
                    result = repo.run_command(
                        f"find . -name '{pattern}' -type f -not -path '*/node_modules/*' 2>/dev/null | head -5"
                    )
                    
                    if result.get('returncode') == 0 and result.get('stdout', '').strip():
                        file_paths = result['stdout'].strip().split('\n')
                        
                        for file_path in file_paths:
                            if file_path:
                                read_result = repo.run_command(f"cat '{file_path}' 2>/dev/null")
                                if read_result.get('returncode') == 0:
                                    files_content[file_path] = read_result.get('stdout', '')
            
            elif hasattr(repo, 'read_file'):
                for pattern in file_patterns:
                    try:
                        content = repo.read_file(pattern)
                        if content:
                            files_content[pattern] = content
                    except Exception:
                        pass
            
            self._log_step('repo_files_read', {
                'files_count': len(files_content), 
                'files': list(files_content.keys())
            })
            
        except Exception as e:
            self._log_step('repo_files_read_error', {'error': str(e)})
        
        return files_content
    
    def _read_test_files(self, repo, test_results: Dict[str, Any]) -> Dict[str, str]:
        test_files = {}
        
        try:
            for error in test_results.get('errors', [])[:5]:
                test_file = error.get('test_file', '')
                
                if test_file and test_file not in test_files:
                    normalized_path = test_file.strip()
                    
                    if hasattr(repo, 'run_command'):
                        read_result = repo.run_command(f"cat '{normalized_path}' 2>/dev/null")
                        if read_result.get('returncode') == 0:
                            test_files[test_file] = read_result.get('stdout', '')
                    
                    elif hasattr(repo, 'read_file'):
                        try:
                            content = repo.read_file(normalized_path)
                            if content:
                                test_files[test_file] = content
                        except Exception:
                            pass
            
            self._log_step('test_files_read', {
                'files_count': len(test_files), 
                'files': list(test_files.keys())
            })
            
        except Exception as e:
            self._log_step('test_files_read_error', {'error': str(e)})
        
        return test_files
    
    def _parse_test_results(self, stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
        results = {
            'success': False,
            'tests_passed': 0,
            'tests_failed': 0,
            'errors': [],
            'raw_output': stdout + stderr,
            'has_open_handles': False,
            'actual_returncode': returncode
        }
        
        combined_output = stdout + stderr
        
        if 'Force exiting Jest' in combined_output or 'detectOpenHandles' in combined_output:
            results['has_open_handles'] = True
        
        try:
            if os.path.exists('jest-results.json'):
                with open('jest-results.json', 'r', encoding='utf-8') as f:
                    jest_data = json.load(f)
                    
                results['tests_passed'] = jest_data.get('numPassedTests', 0)
                results['tests_failed'] = jest_data.get('numFailedTests', 0)
                results['success'] = results['tests_failed'] == 0 and results['tests_passed'] > 0
                
                if 'testResults' in jest_data:
                    for test_result in jest_data['testResults']:
                        if test_result.get('status') == 'failed':
                            for assertion in test_result.get('assertionResults', []):
                                if assertion.get('status') == 'failed':
                                    failure_messages = assertion.get('failureMessages', [])
                                    results['errors'].append({
                                        'test_file': test_result.get('name', ''),
                                        'test_name': assertion.get('fullName', ''),
                                        'error_message': failure_messages[0] if failure_messages else 'Unknown error'
                                    })
            else:
                self._parse_text_output(combined_output, results)
                
        except Exception as e:
            self._log_step('parsing_error', {'error': str(e)})
            results['errors'].append({
                'type': 'parsing_error',
                'message': str(e)
            })
        
        if returncode != 0 and not results['errors']:
            self._extract_runtime_errors(combined_output, results)
        
        return results
    
    def _parse_text_output(self, output: str, results: Dict[str, Any]):
        lines = output.split('\n')
        
        for line in lines:
            if 'Tests:' in line:
                parts = line.split(',')
                for part in parts:
                    if 'passed' in part.lower():
                        try:
                            results['tests_passed'] = int(''.join(filter(str.isdigit, part)))
                        except ValueError:
                            pass
                    elif 'failed' in part.lower():
                        try:
                            results['tests_failed'] = int(''.join(filter(str.isdigit, part)))
                        except ValueError:
                            pass
        
        results['success'] = results['tests_failed'] == 0 and results['tests_passed'] > 0
    
    def _extract_runtime_errors(self, output: str, results: Dict[str, Any]):
        error_keywords = ['Error:', 'FAIL', 'TypeError:', 'ReferenceError:', 'SyntaxError:']
        lines = output.split('\n')
        
        for i, line in enumerate(lines):
            if any(keyword in line for keyword in error_keywords):
                error_context = '\n'.join(lines[i:i+4])
                results['errors'].append({
                    'type': 'runtime_error',
                    'message': error_context.strip()
                })
                break
    
    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.config.get('temperature', 0.7),
                max_tokens=self.config.get('max_tokens', 32000)
            )
            return response.choices[0].message.content
        except Exception as e:
            self._log_step('llm_error', {'error': str(e)})
            raise
    
    def _build_prompt(self, task: Dict[str, Any], build_output: Dict[str, Any], 
                     test_output: Dict[str, Any], iteration: int, 
                     repo_files: Dict[str, str], test_files: Dict[str, str],
                     current_build_command: str, current_test_command: str) -> List[Dict[str, str]]:
        system_prompt = self.config['prompts']['system_prompt']
        
        repo_files_str = "\n\n".join([
            f"=== {path} ===\n{content[:3000]}" 
            for path, content in list(repo_files.items())[:10]
        ])
        
        test_files_str = "\n\n".join([
            f"=== {path} ===\n{content[:4000]}" 
            for path, content in list(test_files.items())[:5]
        ])
        
        errors_str = json.dumps(test_output.get('errors', [])[:10], ensure_ascii=False, indent=2)
        
        open_handles_info = ""
        if test_output.get('has_open_handles'):
            open_handles_info = "\nWARNING: Detected open handles causing Force exiting Jest."
        
        context = {
            'repo_name': task['repo_name'],
            'base_commit': task['base_commit'],
            'build_success': build_output['returncode'] == 0,
            'build_output': build_output['stdout'][-3000:],
            'tests_passed': test_output['tests_passed'],
            'tests_failed': test_output['tests_failed'],
            'success': test_output['success'],
            'errors': errors_str,
            'raw_output': test_output['raw_output'][-3000:],
            'iteration': iteration,
            'max_iterations': self.max_iterations,
            'repo_files': repo_files_str,
            'test_files': test_files_str,
            'open_handles_warning': open_handles_info,
            'actual_returncode': test_output.get('actual_returncode', 'unknown'),
            'current_build_command': current_build_command,
            'current_test_command': current_test_command
        }
        
        user_prompt = self.config['prompts']['user_prompt_template'].format(**context)
        
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
        
        if iteration > 0:
            history_context = self._build_history_context()
            if history_context:
                messages.append({'role': 'user', 'content': history_context})
        
        return messages
    
    def _build_history_context(self) -> str:
        history = []
        
        for step in self.trajectory[-6:]:
            if step['step_type'] == 'commands_generated':
                data = step['data']
                history.append(
                    f"=== Previous attempt iteration {data.get('iteration', '?')} ===\n"
                    f"Build command: {data.get('build_command', 'N/A')}\n"
                    f"Test command: {data.get('test_command', 'N/A')}"
                )
            elif step['step_type'] == 'test_run_complete':
                results = step['data'].get('parsed_results', {})
                history.append(
                    f"Result: passed={results.get('tests_passed', 0)}, "
                    f"failed={results.get('tests_failed', 0)}, "
                    f"success={results.get('success', False)}, "
                    f"returncode={results.get('actual_returncode', '?')}"
                )
        
        return "\n\n".join(history) if history else ""
    
    def _extract_commands(self, text: str) -> Dict[str, Optional[str]]:
        commands = {
            'build_command': None,
            'test_command': None
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if line_lower.startswith('build_command:') or line_lower.startswith('build:'):
                command_part = line.split(':', 1)[1].strip()
                command_part = self._clean_command(command_part)
                if command_part:
                    commands['build_command'] = command_part
            
            elif line_lower.startswith('test_command:') or line_lower.startswith('test:'):
                command_part = line.split(':', 1)[1].strip()
                command_part = self._clean_command(command_part)
                if command_part:
                    commands['test_command'] = command_part
        
        if '```bash' in text or '```sh' in text:
            bash_blocks = []
            for marker in ['```bash', '```sh']:
                if marker in text:
                    parts = text.split(marker)
                    for i in range(1, len(parts)):
                        block = parts[i].split('```', 1)[0].strip()
                        if block:
                            bash_blocks.append(block)
            
            if len(bash_blocks) >= 2:
                commands['build_command'] = bash_blocks[0]
                commands['test_command'] = bash_blocks[1]
            elif len(bash_blocks) == 1:
                if not commands['build_command'] and not commands['test_command']:
                    commands['test_command'] = bash_blocks[0]
        
        return commands
    
    def _clean_command(self, command: str) -> str:
        command = command.strip()
        
        for quote in ['"', "'", '`']:
            if command.startswith(quote) and command.endswith(quote):
                command = command[1:-1]
        
        return command.strip()
    
    def run(self, task: Dict[str, Any], repo) -> Dict[str, Any]:
        self._log_step('agent_start', {
            'task_id': task['task_id'],
            'instance_id': task['instance_id'],
            'repo': task['repo_name']
        })
        
        repo_files = self._read_repo_files(repo)
        
        current_build_command = (
            "npm ci --legacy-peer-deps --loglevel=error 2>/dev/null || "
            "npm install --legacy-peer-deps --loglevel=error 2>/dev/null; "
            "npm install jest --save-dev --legacy-peer-deps --loglevel=error 2>/dev/null; "
            "exit 0"
        )
        
        current_test_command = task['command_test']
        if '|| true' not in current_test_command and '; exit 0' not in current_test_command:
            current_test_command = f"({current_test_command}) || true"
        
        iteration = 0
        last_error_signature = None
        
        while iteration < self.max_iterations:
            self._log_step('build_env_start', {'iteration': iteration})
            
            build_result = repo.build_env(current_build_command)
            
            self._log_step('build_env_complete', {
                'iteration': iteration,
                'returncode': build_result['returncode'],
                'success': build_result['returncode'] == 0,
                'command': current_build_command
            })
            
            if build_result['returncode'] != 0 and 'fatal' in build_result.get('stderr', '').lower():
                return self._return_with_fail(
                    'build_failed', 
                    'Critical build environment error',
                    build_result
                )
            
            self._log_step('test_run_start', {'iteration': iteration})
            
            test_result = repo.run_test(current_test_command)
            parsed_results = self._parse_test_results(
                test_result.get('stdout', ''),
                test_result.get('stderr', ''),
                test_result.get('returncode', 1)
            )
            
            self._log_step('test_run_complete', {
                'iteration': iteration,
                'tests_passed': parsed_results['tests_passed'],
                'tests_failed': parsed_results['tests_failed'],
                'success': parsed_results['success'],
                'error_count': len(parsed_results['errors']),
                'returncode': parsed_results['actual_returncode'],
                'command': current_test_command
            })
            
            if parsed_results['success'] and test_result.get('returncode', 1) == 0:
                return self._return_with_success(parsed_results, iteration)
            
            current_error_signature = self._get_error_signature(parsed_results)
            if current_error_signature == last_error_signature and iteration > 0:
                self._log_step('loop_detected', {
                    'iteration': iteration,
                    'error_signature': current_error_signature
                })
            
            last_error_signature = current_error_signature
            
            test_files = self._read_test_files(repo, parsed_results)
            
            self._log_step('llm_call_start', {'iteration': iteration})
            
            messages = self._build_prompt(
                task,
                build_result,
                parsed_results,
                iteration,
                repo_files,
                test_files,
                current_build_command,
                current_test_command
            )
            
            try:
                llm_response = self._call_llm(messages)
            except Exception as e:
                self._log_step('llm_call_failed', {'error': str(e)})
                iteration += 1
                continue
            
            self._log_step('llm_call_complete', {
                'iteration': iteration,
                'response_length': len(llm_response)
            })
            
            extracted_commands = self._extract_commands(llm_response)
            
            if extracted_commands['build_command']:
                current_build_command = extracted_commands['build_command']
            
            if extracted_commands['test_command']:
                current_test_command = extracted_commands['test_command']
            
            self._log_step('commands_generated', {
                'iteration': iteration,
                'build_command': current_build_command,
                'test_command': current_test_command,
                'llm_response_preview': llm_response[:500]
            })
            
            iteration += 1
        
        return self._return_with_fail(
            'max_iterations_reached',
            f'Failed to fix tests within {self.max_iterations} iterations',
            parsed_results
        )
    
    def _get_error_signature(self, results: Dict[str, Any]) -> str:
        errors = results.get('errors', [])
        if not errors:
            return f"no_errors_{results.get('tests_failed', 0)}"
        
        signature_parts = []
        for error in errors[:3]:
            error_type = error.get('type', 'unknown')
            test_file = error.get('test_file', '')
            test_name = error.get('test_name', '')
            signature_parts.append(f"{error_type}:{test_file}:{test_name}")
        
        return '|'.join(signature_parts)
    
    def _return_with_success(self, results: Dict[str, Any], iterations: int) -> Dict[str, Any]:
        final_result = {
            'status': 'success',
            'iterations': iterations,
            'tests_passed': results['tests_passed'],
            'tests_failed': results['tests_failed'],
            'summary': (
                f"Tests passed successfully after {iterations} iterations. "
                f"Passed: {results['tests_passed']}, Failed: {results['tests_failed']}"
            ),
        }
        
        self._log_step('agent_complete', final_result.copy())
        final_result['trajectory'] = self.trajectory
        return final_result
    
    def _return_with_fail(self, reason: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        final_result = {
            'status': 'failed',
            'reason': reason,
            'message': message,
            'details': details or {},
        }
        
        self._log_step('agent_failed', final_result.copy())
        final_result['trajectory'] = self.trajectory
        return final_result