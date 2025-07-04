import xml.etree.ElementTree as ET
import os

POM_NS = "http://maven.apache.org/POM/4.0.0"


class PomFileFixer:
    REQUIRED_DEPENDENCIES = [
        {"groupId": "org.junit.jupiter", "artifactId": "junit-jupiter", "version": "5.8.1"},
        {"groupId": "org.testcontainers", "artifactId": "junit-jupiter", "version": "1.19.3"},
        {"groupId": "org.mockito", "artifactId": "mockito-core", "version": "4.6.0"},
        {"groupId": "org.mockito", "artifactId": "mockito-inline", "version": "4.6.0"},
        {"groupId": "io.projectreactor", "artifactId": "reactor-test", "version": "3.6.2"},
        {"groupId": "io.projectreactor", "artifactId": "reactor-core", "version": "3.6.2"},
        {"groupId": "org.assertj", "artifactId": "assertj-core", "version": "3.19.0"},
    ]

    @staticmethod
    def dependency_exists(dependencies, group_id, artifact_id, namespaces):
        for dependency in dependencies.findall('ns:dependency', namespaces):
            group_id_elem = dependency.find('ns:groupId', namespaces)
            artifact_id_elem = dependency.find('ns:artifactId', namespaces)
            if group_id_elem is not None and artifact_id_elem is not None:
                if group_id_elem.text == group_id and artifact_id_elem.text == artifact_id:
                    return True
        return False

    def fix_pom_file(self, fn_pom):
        tree = ET.parse(fn_pom)
        root = tree.getroot()
        namespaces = {'ns': POM_NS}

        dependencies = root.find('ns:dependencies', namespaces)
        if dependencies is None:
            dependencies = ET.SubElement(root, 'dependencies')

        for required_dep in self.REQUIRED_DEPENDENCIES:
            if not self.dependency_exists(dependencies, required_dep['groupId'], required_dep['artifactId'], namespaces):
                new_dependency = ET.SubElement(dependencies, 'dependency')
                ET.SubElement(new_dependency, 'groupId').text = required_dep['groupId']
                ET.SubElement(new_dependency, 'artifactId').text = required_dep['artifactId']
                ET.SubElement(new_dependency, 'version').text = required_dep['version']

        self.remove_namespace_prefix(tree, "{%s}"%POM_NS)
        # ET.register_namespace('', POM_NS) ToDo: delete after testing
        tree.write(fn_pom, encoding='UTF-8', xml_declaration=True)
        print("Dependencies checked and updated in pom.xml=%s"%fn_pom)

    @staticmethod
    def remove_namespace_prefix(tree, namespace):
        for elem in tree.iter():
            if elem.tag.startswith(namespace):
                elem.tag = elem.tag.split('}', 1)[1]

    def fix_pom_file_in_package(self, repo_folder):
        fn_pom = os.path.join(repo_folder, 'pom.xml')
        if not os.path.exists(fn_pom):
            fn_pom = os.path.join(repo_folder, 'java', 'pom.xml')

        if not os.path.exists(fn_pom):
            raise ValueError("Couldn't find pom file")
        print("fn_pom=%s"%fn_pom)
        self.fix_pom_file(fn_pom)

    @staticmethod
    def insert_jacoco_into_pom_xml(repo_folder: str):
        
        jacoco_version = '0.8.12'
        jacoco_group_id = 'org.jacoco'
        jacoco_artifact_id = 'jacoco-maven-plugin'

        pom_xml_path = os.path.join(repo_folder, 'pom.xml')
        if not os.path.exists(pom_xml_path):
            pom_xml_path = os.path.join(repo_folder, 'java', 'pom.xml')

        if not os.path.exists(pom_xml_path):
            raise ValueError("Couldn't find pom file")

        tree = ET.parse(pom_xml_path)
        root = tree.getroot()
        ns = {'m': POM_NS}
        ET.register_namespace('', ns['m'])

        build = root.find('m:build', ns)
        plugins = None
        if build is not None:
            plugins = build.find('m:plugins', ns)

        plugin_found = False
        correct_version = False

        if plugins is not None:
            for plugin in plugins.findall('m:plugin', ns):
                group_id = plugin.find('m:groupId', ns)
                artifact_id = plugin.find('m:artifactId', ns)
                version = plugin.find('m:version', ns)
                if (group_id is not None and group_id.text == jacoco_group_id and
                        artifact_id is not None and artifact_id.text == jacoco_artifact_id):
                    plugin_found = True
                    if version is not None and version.text == jacoco_version:
                        correct_version = True
                    break

        # No update needed
        if plugin_found and correct_version:
            return

        # Create or update jacoco plugin
        if build is None:
            build = ET.SubElement(root, 'build')
        if plugins is None:
            plugins = ET.SubElement(build, 'plugins')

        if not plugin_found:
            plugin = ET.SubElement(plugins, 'plugin')
            ET.SubElement(plugin, 'groupId').text = jacoco_group_id
            ET.SubElement(plugin, 'artifactId').text = jacoco_artifact_id
            ET.SubElement(plugin, 'version').text = jacoco_version

            executions = ET.SubElement(plugin, 'executions')

            exec_prepare = ET.SubElement(executions, 'execution')
            ET.SubElement(exec_prepare, 'id').text = 'prepare-agent'
            goals_prepare = ET.SubElement(exec_prepare, 'goals')
            ET.SubElement(goals_prepare, 'goal').text = 'prepare-agent'

            exec_report = ET.SubElement(executions, 'execution')
            ET.SubElement(exec_report, 'id').text = 'report'
            ET.SubElement(exec_report, 'phase').text = 'test'
            goals_report = ET.SubElement(exec_report, 'goals')
            ET.SubElement(goals_report, 'goal').text = 'report'

        else:
            # update the version if plugin exists with wrong version
            for plugin in plugins.findall('m:plugin', ns):
                artifact_id = plugin.find('m:artifactId', ns)
                if artifact_id is not None and artifact_id.text == jacoco_artifact_id:
                    version = plugin.find('m:version', ns)
                    if version is None:
                        version = ET.SubElement(plugin, 'version')
                    version.text = jacoco_version
                    break

        tree.write(pom_xml_path, encoding='utf-8', xml_declaration=True)
