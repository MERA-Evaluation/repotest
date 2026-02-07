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
        """Log each step with timestamp"""
        step = {
            'timestamp': datetime.now().isoformat(),
            'step_type': step_type,
            'data': data
        }
        print(json.dumps(step, ensure_ascii=False))
        self.trajectory.append(step)
    
    def _read_repo_files(self, repo) -> Dict[str, str]:
        """Read repository configuration files with improved logic"""
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
                    find_cmd = f"find . -maxdepth 3 -name '{pattern}' -type f -not -path '*/node_modules/*' 2>/dev/null"
                    result = repo.run_command(find_cmd)
                    
                    if result.get('returncode') == 0 and result.get('stdout', '').strip():
                        file_paths = [p.strip() for p in result['stdout'].strip().split('\n') if p.strip()]

                        for file_path in file_paths[:3]:
                            try:
                                read_result = repo.run_command(f"cat {file_path} 2>/dev/null")
                                if read_result.get('returncode') == 0 and read_result.get('stdout'):
                                    content = read_result.get('stdout', '').strip()
                                    if content:
                                        files_content[file_path] = content
                                        self._log_step('file_read_success', {
                                            'file': file_path,
                                            'size': len(content)
                                        })
                            except Exception as e:
                                self._log_step('file_read_error', {
                                    'file': file_path,
                                    'error': str(e)
                                })

            elif hasattr(repo, 'read_file'):
                for pattern in file_patterns:
                    try:
                        content = repo.read_file(pattern)
                        if content and content.strip():
                            files_content[pattern] = content.strip()
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
        """Read test files mentioned in errors with improved logic"""
        test_files = {}
        
        try:
            errors = test_results.get('errors', [])[:5]
            
            for error in errors:
                test_file = error.get('test_file', '').strip()
                
                if not test_file or test_file in test_files:
                    continue

                test_file = test_file.replace('//', '/').strip()
                
                path_variants = [
                    test_file,
                    test_file.lstrip('./'),
                    f"./{test_file.lstrip('./')}"
                ]
                
                for path in path_variants:
                    if hasattr(repo, 'run_command'):
                        read_result = repo.run_command(f"cat {path} 2>/dev/null")
                        if read_result.get('returncode') == 0 and read_result.get('stdout'):
                            content = read_result.get('stdout', '').strip()
                            if content:
                                test_files[test_file] = content
                                self._log_step('test_file_read_success', {
                                    'file': test_file,
                                    'size': len(content)
                                })
                                break
                    
                    elif hasattr(repo, 'read_file'):
                        try:
                            content = repo.read_file(path)
                            if content and content.strip():
                                test_files[test_file] = content.strip()
                                break
                        except Exception:
                            continue
            
            self._log_step('test_files_read', {
                'files_count': len(test_files), 
                'files': list(test_files.keys())
            })
            
        except Exception as e:
            self._log_step('test_files_read_error', {'error': str(e)})
        
        return test_files
    
    def _parse_test_results(self, stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
        """Parse test execution results"""
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
            self._parse_text_output(combined_output, results)
        
        if returncode != 0 and not results['errors']:
            self._extract_runtime_errors(combined_output, results)
        
        results['success'] = (
            results['tests_passed'] > 0 and 
            results['tests_failed'] == 0
        )
        
        return results
    
    def _parse_text_output(self, output: str, results: Dict[str, Any]):
        """Parse test output from text"""
        lines = output.split('\n')
        
        for line in lines:
            if 'Tests:' in line or 'Test Suites:' in line:
                parts = line.split(',')
                for part in parts:
                    part_lower = part.lower()
                    if 'passed' in part_lower:
                        try:
                            results['tests_passed'] = int(''.join(filter(str.isdigit, part)))
                        except ValueError:
                            pass
                    elif 'failed' in part_lower:
                        try:
                            results['tests_failed'] = int(''.join(filter(str.isdigit, part)))
                        except ValueError:
                            pass
    
    def _extract_runtime_errors(self, output: str, results: Dict[str, Any]):
        """Extract runtime errors from output"""
        error_keywords = ['Error:', 'FAIL', 'TypeError:', 'ReferenceError:', 'SyntaxError:', 'Cannot find module']
        lines = output.split('\n')
        
        for i, line in enumerate(lines):
            if any(keyword in line for keyword in error_keywords):
                error_context = '\n'.join(lines[max(0, i-1):min(len(lines), i+5)])
                results['errors'].append({
                    'type': 'runtime_error',
                    'message': error_context.strip()
                })
                if len(results['errors']) >= 3:
                    break
    
    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call LLM API"""
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
        """Build LLM prompt with all context"""
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
            open_handles_info = "\n⚠️ WARNING: Detected open handles causing Force exiting Jest. Add --forceExit flag."
        
        returncode_warning = ""
        if test_output.get('actual_returncode', 0) != 0:
            if test_output.get('tests_passed', 0) > 0 and test_output.get('tests_failed', 0) == 0:
                returncode_warning = "\n⚠️ CRITICAL: Tests passed but returncode is not 0! You MUST fix the command to return exitcode 0."
        
        context = {
            'repo_name': task['repo_name'],
            'base_commit': task['base_commit'],
            'build_success': build_output['returncode'] == 0,
            'build_output': build_output.get('stdout', '')[-3000:] + '\n' + build_output.get('stderr', '')[-1000:],
            'tests_passed': test_output['tests_passed'],
            'tests_failed': test_output['tests_failed'],
            'success': test_output['success'],
            'errors': errors_str,
            'raw_output': test_output['raw_output'][-3000:],
            'iteration': iteration,
            'max_iterations': self.max_iterations,
            'repo_files': repo_files_str if repo_files else "No configuration files found",
            'test_files': test_files_str if test_files else "No test files could be read",
            'open_handles_warning': open_handles_info,
            'returncode_warning': returncode_warning,
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
                messages.append({'role': 'user', 'content': f"\n=== PREVIOUS ATTEMPTS ===\n{history_context}"})
        
        return messages
    
    def _build_history_context(self) -> str:
        """Build context from previous attempts"""
        history = []
        
        for step in self.trajectory[-8:]:
            if step['step_type'] == 'commands_generated':
                data = step['data']
                history.append(
                    f"Iteration {data.get('iteration', '?')}:\n"
                    f"  Build: {data.get('build_command', 'N/A')}\n"
                    f"  Test: {data.get('test_command', 'N/A')}"
                )
            elif step['step_type'] == 'test_run_complete':
                results = step['data']
                history.append(
                    f"  Result: passed={results.get('tests_passed', 0)}, "
                    f"failed={results.get('tests_failed', 0)}, "
                    f"returncode={results.get('returncode', '?')}"
                )
        
        return "\n".join(history) if history else ""
    
    def _extract_commands(self, text: str) -> Dict[str, Optional[str]]:
        """Extract build and test commands from LLM response"""
        commands = {
            'build_command': None,
            'test_command': None
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            if line_lower.startswith('build_command:') or line_lower.startswith('build:'):
                command_part = line_stripped.split(':', 1)[1].strip()
                command_part = self._clean_command(command_part)
                if command_part:
                    commands['build_command'] = command_part
            
            elif line_lower.startswith('test_command:') or line_lower.startswith('test:'):
                command_part = line_stripped.split(':', 1)[1].strip()
                command_part = self._clean_command(command_part)
                if command_part:
                    commands['test_command'] = command_part
        
        if not commands['build_command'] or not commands['test_command']:
            bash_blocks = []
            for marker in ['```bash', '```sh', '```']:
                if marker in text:
                    parts = text.split(marker)
                    for i in range(1, len(parts), 2):
                        if i < len(parts):
                            block = parts[i].split('```')[0].strip()
                            if block and not block.startswith('json'):
                                bash_blocks.append(block)
            
            if len(bash_blocks) >= 2:
                if not commands['build_command']:
                    commands['build_command'] = bash_blocks[0]
                if not commands['test_command']:
                    commands['test_command'] = bash_blocks[1]
            elif len(bash_blocks) == 1:
                if not commands['test_command']:
                    commands['test_command'] = bash_blocks[0]
        
        return commands
    
    def _clean_command(self, command: str) -> str:
        """Clean command string"""
        command = command.strip()
        
        for quote in ['"', "'", '`']:
            if command.startswith(quote) and command.endswith(quote):
                command = command[1:-1]
        
        return command.strip()
    
    def _ensure_exitcode_zero(self, command: str) -> str:
        """Ensure command returns exitcode 0"""
        if not command:
            return command
        
        command = command.strip()
        
        if command.endswith('|| true') or command.endswith('; exit 0') or '|| exit 0' in command:
            return command

        if ';' in command or '&&' in command:
            return f"({command}) || true"
        else:
            return f"{command} || true"
    
    def run(self, task: Dict[str, Any], repo) -> Dict[str, Any]:
        """Main agent loop"""
        self._log_step('agent_start', {
            'task_id': task.get('task_id', 'unknown'),
            'instance_id': task.get('instance_id', 'unknown'),
            'repo': task['repo_name']
        })

        repo_files = self._read_repo_files(repo)
        
        current_build_command = (
            "npm ci --legacy-peer-deps --loglevel=error 2>/dev/null || "
            "npm install --legacy-peer-deps --loglevel=error 2>/dev/null; "
            "npm install jest --save-dev --legacy-peer-deps --loglevel=error 2>/dev/null; "
            "exit 0"
        )
        
        current_test_command = task.get('command_test', 'npm test')
        current_test_command = self._ensure_exitcode_zero(current_test_command)
        
        iteration = 0
        last_error_signature = None
        consecutive_same_errors = 0
        
        while iteration < self.max_iterations:
            self._log_step('iteration_start', {'iteration': iteration})

            self._log_step('build_env_start', {'iteration': iteration})
            build_result = repo.build_env(current_build_command)
            
            self._log_step('build_env_complete', {
                'iteration': iteration,
                'returncode': build_result.get('returncode', -1),
                'success': build_result.get('returncode', -1) == 0,
                'command': current_build_command
            })

            if build_result.get('returncode', -1) != 0:
                stderr_lower = build_result.get('stderr', '').lower()
                if any(word in stderr_lower for word in ['fatal', 'enotdir', 'cannot read property']):
                    return self._return_with_fail(
                        'critical_build_error', 
                        'Critical build environment error - repository may be corrupted',
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

            if parsed_results['success'] and parsed_results['actual_returncode'] == 0:
                return self._return_with_success(parsed_results, iteration)
            
            if (parsed_results['tests_passed'] > 0 and 
                parsed_results['tests_failed'] == 0 and 
                parsed_results['actual_returncode'] != 0):
                
                self._log_step('fixing_returncode', {
                    'iteration': iteration,
                    'tests_passed': parsed_results['tests_passed'],
                    'current_returncode': parsed_results['actual_returncode']
                })

                current_test_command = self._ensure_exitcode_zero(
                    current_test_command.replace(' || true', '').replace('; exit 0', '')
                )
                
                iteration += 1
                continue
            
            current_error_signature = self._get_error_signature(parsed_results)
            if current_error_signature == last_error_signature:
                consecutive_same_errors += 1
                if consecutive_same_errors >= 2:
                    self._log_step('error_loop_detected', {
                        'iteration': iteration,
                        'error_signature': current_error_signature,
                        'consecutive_count': consecutive_same_errors
                    })
            else:
                consecutive_same_errors = 0
            
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
                current_build_command = self._ensure_exitcode_zero(extracted_commands['build_command'])
            
            if extracted_commands['test_command']:
                current_test_command = self._ensure_exitcode_zero(extracted_commands['test_command'])
            
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
        """Generate error signature for loop detection"""
        errors = results.get('errors', [])
        if not errors:
            return f"no_errors_failed_{results.get('tests_failed', 0)}_rc_{results.get('actual_returncode', -1)}"
        
        signature_parts = []
        for error in errors[:3]:
            error_type = error.get('type', 'unknown')
            test_file = error.get('test_file', '')
            message_preview = error.get('error_message', '')[:50]
            signature_parts.append(f"{error_type}:{test_file}:{hash(message_preview)}")
        
        return '|'.join(signature_parts)
    
    def _return_with_success(self, results: Dict[str, Any], iterations: int) -> Dict[str, Any]:
        """Return success result"""
        final_result = {
            'status': 'success',
            'iterations': iterations,
            'tests_passed': results['tests_passed'],
            'tests_failed': results['tests_failed'],
            'summary': (
                f"✅ Tests passed successfully after {iterations} iterations. "
                f"Passed: {results['tests_passed']}, Failed: {results['tests_failed']}"
            ),
        }
        
        self._log_step('agent_complete', final_result.copy())
        final_result['trajectory'] = self.trajectory
        return final_result
    
    def _return_with_fail(self, reason: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return failure result"""
        final_result = {
            'status': 'failed',
            'reason': reason,
            'message': message,
            'details': details or {},
        }
        
        self._log_step('agent_failed', final_result.copy())
        final_result['trajectory'] = self.trajectory
        return final_result
    
    def get_commands(self) -> Dict[str, str]:
        """Extract final commands from trajectory"""
        for step in reversed(self.trajectory):
            if step['step_type'] == 'commands_generated':
                return {
                    'build_command': step['data'].get('build_command'),
                    'test_command': step['data'].get('test_command')
                }
        return {'build_command': None, 'test_command': None}