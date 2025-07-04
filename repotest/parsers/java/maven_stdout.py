import re
import logging
logger = logging.getLogger("repotest") 

def extract_assertion_errors(idx, line, lines, errors):
    method_name_pattern = r'\.([a-zA-Z_][a-zA-Z0-9_]*)\('
    assertion_error_pattern = 'AssertionFailedError:'
    if assertion_error_pattern in line:
        rest_of_line = line[line.find(assertion_error_pattern) + len(assertion_error_pattern):]
        method_name = None
        if idx < len(lines) - 1:
            next_line = lines[idx + 1]
            if next_line.startswith("\tat "):
                match = re.search(method_name_pattern, next_line)
                if match:
                    method_name = match.group(1)
        errors.append({"text": rest_of_line, "method": method_name})


def extract_runtime_errors(idx, line, lines, errors):
    method_name_pattern = r'\.([a-zA-Z_][a-zA-Z0-9_]*)\('
    runtime_error_pattern = 'Exception:'
    if runtime_error_pattern in line and line.startswith("java."):
        rest_of_line = line[line.find(runtime_error_pattern) + len(runtime_error_pattern):]
        method_name = None
        if idx < len(lines) - 1:
            next_line = lines[idx + 1]
            if next_line.startswith("\tat "):
                match = re.search(method_name_pattern, next_line)
                if match:
                    method_name = match.group(1)
        errors.append({"text": rest_of_line, "method": method_name})


def extract_compile_errors(full_path, idx, line, lines, errors):
    error_type_pattern = r'\[\d+,\d+\]\s+(.+)'
    if full_path in line and line.startswith("[ERROR]"):
        match = re.search(error_type_pattern, line)
        error_type = "unknown"
        details = None
        if match:
            error_type = match.group(1)
        if idx < len(lines) - 1:
            next_line = lines[idx + 1]
            details = None
            if next_line.startswith("[ERROR]") and len(next_line) > 20:
                if not re.search(error_type_pattern, next_line):
                    details = next_line[8:].strip()
        errors.append({"type": error_type, "details": details})


def analyze_maven_stdout(stdout, full_path, collect_errors = False):
    #ToDo: collect errors = True => compile_rate = compile_rate / 5
    error_type_pattern = r'\[\d+,\d+\]\s+(.+)'
    if isinstance(stdout, bytes):
        lines = stdout.decode("utf-8").split("\n")
    elif isinstance(stdout, str):
        lines = stdout.split('\n')
    else:
        raise ValueError("Unknown type of stdout")
    
    result = {"success": False, "tests": 0, "compiled": False, "errors": []}
    last_error = None
    assertion_errors = []
    compile_errors = []
    runtime_errors = []
    for i, line in enumerate(lines):
        if line.startswith("[INFO] BUILD SUCCESS"):
            result["success"] = True
        if line.startswith("[INFO]  T E S T S"):
            result["compiled"] = True
        if line.startswith("[INFO] Tests run:"):
            parts = line.split(",")
            for part in parts:
                if "Tests run" in part:
                    result["tests"] = int(part.split(":")[1].strip())

        if line.startswith("[ERROR]"):
            match = re.search(error_type_pattern, line)
            error_type = "unknown"
            if match:
                error_type = match.group(1)
                if "has private access in" in error_type:
                    error_type = "private_access"
                elif "cannot find symbol" in error_type:
                    error_type = "symbol_not_found"
                elif "class, interface, enum" in error_type:
                    error_type = "class_interface_enum (repeatance of package declaration)"
                elif "should be declared in a file named" in error_type:
                    error_type = "file_name"
                    logger.warning("File name error:")
                    logger.warning(full_path)
                    logger.warning(line)

                elif ("reached end of file while parsing" in error_type
                      or "unclosed string literal" in error_type):
                    error_type = "end_of_file"
                elif "cannot be instantiated" in error_type:
                    error_type = "cannot_instantiate_abstract_class"
                elif "reference to with is ambiguous" in error_type:
                    error_type = "ambiguous_reference"
                elif "';' expected" in error_type:
                    error_type = "semicolon_expected"
                else:
                    # error_type = "other"
                    logger.error("Unknown error type: %s"%error_type)
                    logger.error(line)
                last_error = {
                    "type": error_type,
                    "full_text": line,
                }

        elif last_error:
            last_error["message"] = line
            last_error["full_text"] += "\n" + line
            result["errors"].append(last_error)
            last_error = None

        if collect_errors:
            extract_assertion_errors(i, line, lines, assertion_errors)
            extract_compile_errors(full_path, i, line, lines, compile_errors)
            extract_runtime_errors(i, line, lines, runtime_errors)

    if collect_errors:
        result["assertion_errors"] = assertion_errors
        result["compile_errors"] = compile_errors
        result["runtime_errors"] = runtime_errors
        if result["compile_errors"]:
            result["compiled"] = False
    return result
