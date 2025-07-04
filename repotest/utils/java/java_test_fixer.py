import pandas as pd
class JavaTestFixer:
    def __init__(self):
        pass

    @staticmethod
    def correct_test_code(code):
        if pd.isna(code):
            return ""
        if code.startswith("ckage"):
            return f"pa{code}"
        if code.startswith("age"):
            return f"pack{code}"
        if code.startswith("ackage"):
            return f"p{code}"
        if code.startswith("<|code|>"):
            return code[8:]
        return code

    def find_package_declaration(self, source_code: str) -> str:
        for line in source_code.split("\n"):
            if line.startswith("package "):
                return line
        return None

    def fix_package_declaration(self, source_code: str, test_code: str) -> str:
        package_name = self.find_package_declaration(source_code)
        if package_name is None:
            return test_code
        
        lines = test_code.split("\n")
        result = []
        there_is_package_declaration = False
        
        for line in lines:
            if line.startswith("package "):
                result.append(package_name)
                there_is_package_declaration = True
            else:
                result.append(line)
        
        if not there_is_package_declaration:
            result.insert(0, package_name)
        
        return "\n".join(result)

    @staticmethod
    def extract_imports(java_code: str) -> dict:
        imports = {}
        for line in java_code.split("\n"):
            if line.startswith("import "):
                cleaned_line = line.replace("import ", "").replace("static ", "").rstrip(";")
                imports[cleaned_line] = line
        return imports

    def fix_imports(self, source_code: str, test_code: str) -> str:
        source_imports = self.extract_imports(source_code)
        test_imports = self.extract_imports(test_code)
        missing_imports = {k: v for k, v in source_imports.items() if k not in test_imports}

        lines = test_code.split("\n")
        package_index = next((i for i, line in enumerate(lines) if line.startswith("package ")), -1)
        if package_index != -1:
            result = lines[:package_index + 1] + list(missing_imports.values()) + lines[package_index + 1:]
        else:
            result = list(missing_imports.values()) + lines
        
        return "\n".join(result)

    def fix_test(self, source_code: str, test_code: str) -> str:
        test_code = self.fix_package_declaration(source_code, test_code)
        return self.fix_imports(source_code, test_code)

    def correct_code(self, source_code, test_code):
        corrected_code = self.correct_test_code(test_code)
        corrected_code = self.fix_test(source_code, corrected_code)
        
        if corrected_code == test_code:
            print("Code not changed")
        else:
            print("Code changed")
        
        return corrected_code
