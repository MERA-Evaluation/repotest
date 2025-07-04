import javalang
from javalang.tree import (
    ClassDeclaration, VariableDeclaration, MethodDeclaration,
    ConstructorDeclaration, BasicType, ReferenceType, LocalVariableDeclaration
)
from typing import List, Dict, Optional

class JavaParser:
    """
    A class to parse Java source and test code using javalang.
    """

    @staticmethod
    def parse_code(code: str) -> Optional[javalang.tree.CompilationUnit]:
        """
        Parses Java code into an AST.

        Parameters
        ----------
        code : str
            Java source code as a string.

        Returns
        -------
        Optional[javalang.tree.CompilationUnit]
            Parsed AST if successful, None otherwise.
        """
        try:
            return javalang.parse.parse(code)
        except javalang.parser.JavaSyntaxError:
            return None

    @staticmethod
    def get_type_representation(node: javalang.tree.Type) -> str:
        """
        Extracts type representation from a Java AST node.

        Parameters
        ----------
        node : javalang.tree.Type
            A Java type node.

        Returns
        -------
        str
            A string representation of the type.
        """
        if isinstance(node, BasicType):
            return node.name
        if isinstance(node, ReferenceType):
            return node.name
        return "UnknownType"

class JavaAnalyzer:
    """
    A class to analyze Java code structure and test coverage.
    """
    
    def __init__(self, source_code: str, test_code: str):
        self.source_code = source_code
        self.test_code = test_code
        self.source_class = self.extract_class_properties(self.source_code)
        self.test_class = self.extract_class_properties(self.test_code)
    
    def extract_class_properties(self, code: str) -> Optional[Dict[str, List[Dict[str, str]]]]:
        """
        Extracts class properties including methods and fields.

        Parameters
        ----------
        code : str
            Java source code.

        Returns
        -------
        Optional[Dict[str, List[Dict[str, str]]]]
            Dictionary containing class fields and methods.
        """
        tree = JavaParser.parse_code(code)
        if not tree:
            return None

        fields, methods = [], []
        class_name = None
        source_lines = code.split("\n")
        
        for path, node in tree:
            if isinstance(node, ClassDeclaration):
                class_name = node.name
            elif isinstance(node, VariableDeclaration) and not isinstance(node, LocalVariableDeclaration):
                fields.append({"name": node.declarators[0].name})
            elif isinstance(node, (MethodDeclaration, ConstructorDeclaration)):
                method_data = {
                    "name": node.name,
                    "parameters": [JavaParser.get_type_representation(param.type) for param in node.parameters],
                    "body": []
                }
                if node.body:
                    method_data["body"] = [source_lines[stmt.position[0] - 1].strip() for stmt in node.body if hasattr(stmt, "position")]
                methods.append(method_data)
        
        return {"name": class_name, "fields": fields, "methods": methods} if class_name else None

    def get_method_reference_count(self, method_name: str) -> int:
        """
        Counts the number of times a method is referenced in test code.

        Parameters
        ----------
        method_name : str
            The method name to check for references.

        Returns
        -------
        int
            Number of times the method is referenced in test assertions.
        """
        if not self.test_class:
            return 0

        references = 0
        snippet = f".{method_name}("

        for method in self.test_class["methods"]:
            for line in method.get("body", []):
                if snippet in line or f"assert" in line and method_name in line:
                    references += 1
        return references

    def compute_test_coverage(self) -> Optional[Dict[str, int]]:
        """
        Computes test coverage by counting method references.

        Returns
        -------
        Optional[Dict[str, int]]
            A dictionary containing method count and reference count.
        """
        if not self.source_class:
            return None

        method_count = len(self.source_class["methods"])
        ref_count = sum(self.get_method_reference_count(m["name"]) for m in self.source_class["methods"])
        
        return {"methods_count": method_count, "refs_count": ref_count}

# Example usage
source_code = """public class Calculator {
    public int add(int a, int b) { return a + b; }
    public int subtract(int a, int b) { return a - b; }
    public int multiply(int a, int b) { return a * b; }
    public double divide(int a, int b) {
        if (b == 0) { throw new IllegalArgumentException("Cannot divide by zero"); }
        return (double) a / b;
    }
}"""

test_code = """import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CalculatorTest {
    private final Calculator calculator = new Calculator();

    @Test void testAdd() { assertEquals(5, calculator.add(2, 3)); }
    @Test void testSubtract() { assertEquals(1, calculator.subtract(4, 3)); }
    @Test void testMultiply() { assertEquals(12, calculator.multiply(4, 3)); }
    @Test void testDivide() { assertEquals(2.0, calculator.divide(6, 3)); }
    @Test void testDivideByZero() {
        Exception e = assertThrows(IllegalArgumentException.class, () -> calculator.divide(6, 0));
        assertEquals("Cannot divide by zero", e.getMessage());
    }
}"""

analyzer = JavaAnalyzer(source_code, test_code)
print(analyzer.compute_test_coverage())
