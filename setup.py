"""A setuptools based setup module.

"""
from __future__ import print_function

import os
import fnmatch
import re
import sys
import subprocess
import yaml

# Always prefer setuptools over distutils
from setuptools import setup, Command
from setuptools_lint.setuptools_command import PylintCommand
from six import string_types
from six.moves import reload_module
from yamllint.config import YamlLintConfig
from yamllint.cli import Format
from yamllint import linter


def find_files(base_dir, exclude_dirs, include_dirs, file_regex):
    ''' find files matching file_regex '''
    found = []
    exclude_regex = ''
    include_regex = ''

    if exclude_dirs is not None:
        exclude_regex = r'|'.join([fnmatch.translate(x) for x in exclude_dirs]) or r'$.'

    # Don't use include_dirs, it is broken
    if include_dirs is not None:
        include_regex = r'|'.join([fnmatch.translate(x) for x in include_dirs]) or r'$.'

    for root, dirs, files in os.walk(base_dir):
        if exclude_dirs is not None:
            # filter out excludes for dirs
            dirs[:] = [d for d in dirs if not re.match(exclude_regex, d)]

        if include_dirs is not None:
            # filter for includes for dirs
            dirs[:] = [d for d in dirs if re.match(include_regex, d)]

        matches = [os.path.join(root, f) for f in files if re.search(file_regex, f) is not None]
        found.extend(matches)

    return found


def find_entrypoint_playbooks():
    '''find entry point playbooks as defined by openshift-ansible'''
    playbooks = set()
    included_playbooks = set()

    exclude_dirs = ['adhoc', 'tasks']
    for yaml_file in find_files(
            os.path.join(os.getcwd(), 'playbooks'),
            exclude_dirs, None, r'\.ya?ml$'):
        with open(yaml_file, 'r') as contents:
            for task in yaml.safe_load(contents):
                if not isinstance(task, dict):
                    # Skip yaml files which are not a dictionary of tasks
                    continue
                if 'include' in task:
                    # Add the playbook and capture included playbooks
                    playbooks.add(yaml_file)
                    included_file_name = task['include'].split()[0]
                    included_file = os.path.normpath(
                        os.path.join(os.path.dirname(yaml_file),
                                     included_file_name))
                    included_playbooks.add(included_file)
                elif 'hosts' in task:
                    playbooks.add(yaml_file)
    # Evaluate the difference between all playbooks and included playbooks
    entrypoint_playbooks = sorted(playbooks.difference(included_playbooks))
    print('Entry point playbook count: {}'.format(len(entrypoint_playbooks)))
    return entrypoint_playbooks


class OpenShiftAnsibleYamlLint(Command):
    ''' Command to run yamllint '''
    description = "Run yamllint tests"
    user_options = [
        ('excludes=', 'e', 'directories to exclude'),
        ('config-file=', 'c', 'config file to use'),
        ('format=', 'f', 'format to use (standard, parsable)'),
    ]

    def initialize_options(self):
        ''' initialize_options '''
        # Reason: Defining these attributes as a part of initialize_options is
        # consistent with upstream usage
        # Status: permanently disabled
        # pylint: disable=attribute-defined-outside-init
        self.excludes = None
        self.config_file = None
        self.format = None

    def finalize_options(self):
        ''' finalize_options '''
        # Reason: These attributes are defined in initialize_options and this
        # usage is consistant with upstream usage
        # Status: permanently disabled
        # pylint: disable=attribute-defined-outside-init
        if isinstance(self.excludes, string_types):
            self.excludes = self.excludes.split(',')
        if self.format is None:
            self.format = 'standard'
        assert (self.format in ['standard', 'parsable']), (
            'unknown format {0}.'.format(self.format))
        if self.config_file is None:
            self.config_file = '.yamllint'
        assert os.path.isfile(self.config_file), (
            'yamllint config file {0} does not exist.'.format(self.config_file))

    def run(self):
        ''' run command '''
        if self.excludes is not None:
            print("Excludes:\n{0}".format(yaml.dump(self.excludes, default_flow_style=False)))

        config = YamlLintConfig(file=self.config_file)

        has_errors = False
        has_warnings = False

        if self.format == 'parsable':
            format_method = Format.parsable
        else:
            format_method = Format.standard_color

        for yaml_file in find_files(os.getcwd(), self.excludes, None, r'\.ya?ml$'):
            first = True
            with open(yaml_file, 'r') as contents:
                for problem in linter.run(contents, config):
                    if first and self.format != 'parsable':
                        print('\n{0}:'.format(os.path.relpath(yaml_file)))
                        first = False

                    print(format_method(problem, yaml_file))
                    if problem.level == linter.PROBLEM_LEVELS[2]:
                        has_errors = True
                    elif problem.level == linter.PROBLEM_LEVELS[1]:
                        has_warnings = True

        if has_errors or has_warnings:
            print('yammlint issues found')
            raise SystemExit(1)


class OpenShiftAnsiblePylint(PylintCommand):
    ''' Class to override the default behavior of PylintCommand '''

    # Reason: This method needs to be an instance method to conform to the
    # overridden method's signature
    # Status: permanently disabled
    # pylint: disable=no-self-use
    def find_all_modules(self):
        ''' find all python files to test '''
        exclude_dirs = ['.tox', 'utils', 'test', 'tests', 'git']
        modules = []
        for match in find_files(os.getcwd(), exclude_dirs, None, r'\.py$'):
            package = os.path.basename(match).replace('.py', '')
            modules.append(('openshift_ansible', package, match))
        return modules

    def get_finalized_command(self, cmd):
        ''' override get_finalized_command to ensure we use our
        find_all_modules method '''
        if cmd == 'build_py':
            return self

    # Reason: This method needs to be an instance method to conform to the
    # overridden method's signature
    # Status: permanently disabled
    # pylint: disable=no-self-use
    def with_project_on_sys_path(self, func, func_args, func_kwargs):
        ''' override behavior, since we don't need to build '''
        return func(*func_args, **func_kwargs)


class OpenShiftAnsibleGenerateValidation(Command):
    ''' Command to run generated module validation'''
    description = "Run generated module validation"
    user_options = []

    def initialize_options(self):
        ''' initialize_options '''
        pass

    def finalize_options(self):
        ''' finalize_options '''
        pass

    # self isn't used but I believe is required when it is called.
    # pylint: disable=no-self-use
    def run(self):
        ''' run command '''
        # find the files that call generate
        generate_files = find_files('roles',
                                    ['inventory',
                                     'test',
                                     'playbooks',
                                     'utils'],
                                    None,
                                    'generate.py$')

        if len(generate_files) < 1:
            print('Did not find any code generation.  Please verify module code generation.')  # noqa: E501
            raise SystemExit(1)

        errors = False
        for gen in generate_files:
            print('Checking generated module code: {0}'.format(gen))
            try:
                sys.path.insert(0, os.path.dirname(gen))
                # we are importing dynamically.  This isn't in
                # the python path.
                # pylint: disable=import-error
                import generate
                reload_module(generate)
                generate.verify()
            except generate.GenerateAnsibleException as gae:
                print(gae.args)
                errors = True

        if errors:
            print('Found errors while generating module code.')
            raise SystemExit(1)

        print('\nAll generate scripts passed.\n')


class OpenShiftAnsibleSyntaxCheck(Command):
    ''' Command to run Ansible syntax check'''
    description = "Run Ansible syntax check"
    user_options = []

    # Colors
    FAIL = '\033[31m'  # Red
    ENDC = '\033[0m'  # Reset

    def initialize_options(self):
        ''' initialize_options '''
        pass

    def finalize_options(self):
        ''' finalize_options '''
        pass

    def run(self):
        ''' run command '''

        has_errors = False

        print('Ansible Deprecation Checks')
        exclude_dirs = ['adhoc', 'files', 'meta', 'test', 'tests', 'vars', '.tox']
        for yaml_file in find_files(
                os.getcwd(), exclude_dirs, None, r'\.ya?ml$'):
            with open(yaml_file, 'r') as contents:
                for task in yaml.safe_load(contents) or {}:
                    if not isinstance(task, dict):
                        # Skip yaml files which are not a dictionary of tasks
                        continue
                    if 'when' in task:
                        if '{{' in task['when'] or '{%' in task['when']:
                            print('{}Error: Usage of Jinja2 templating delimiters '
                                  'in when conditions is deprecated in Ansible 2.3.\n'
                                  '  File: {}\n'
                                  '  Found: "{}"{}'.format(
                                      self.FAIL, yaml_file,
                                      task['when'], self.ENDC))
                            has_errors = True
                    # TODO (rteague): This test will be enabled once we move to Ansible 2.4
                    # if 'include' in task:
                    #     print('{}Error: The `include` directive is deprecated in Ansible 2.4.\n'
                    #           'https://github.com/ansible/ansible/blob/devel/CHANGELOG.md\n'
                    #           '  File: {}\n'
                    #           '  Found: "include: {}"{}'.format(
                    #               self.FAIL, yaml_file, task['include'], self.ENDC))
                    #     has_errors = True

        print('Ansible Playbook Entry Point Syntax Checks')
        for playbook in find_entrypoint_playbooks():
            print('-' * 60)
            print('Syntax checking playbook: {}'.format(playbook))

            # Error on any entry points in 'common'
            if 'common' in playbook:
                print('{}Invalid entry point playbook. All playbooks must'
                      ' start in playbooks/byo{}'.format(self.FAIL, self.ENDC))
                has_errors = True
            # --syntax-check each entry point playbook
            else:
                try:
                    subprocess.check_output(
                        ['ansible-playbook', '-i localhost,',
                         '--syntax-check', playbook]
                    )
                except subprocess.CalledProcessError as cpe:
                    print('{}Execution failed: {}{}'.format(
                        self.FAIL, cpe, self.ENDC))
                    has_errors = True

        if has_errors:
            raise SystemExit(1)


class UnsupportedCommand(Command):
    ''' Basic Command to override unsupported commands '''
    user_options = []

    # Reason: This method needs to be an instance method to conform to the
    # overridden method's signature
    # Status: permanently disabled
    # pylint: disable=no-self-use
    def initialize_options(self):
        ''' initialize_options '''
        pass

    # Reason: This method needs to be an instance method to conform to the
    # overridden method's signature
    # Status: permanently disabled
    # pylint: disable=no-self-use
    def finalize_options(self):
        ''' initialize_options '''
        pass

    # Reason: This method needs to be an instance method to conform to the
    # overridden method's signature
    # Status: permanently disabled
    # pylint: disable=no-self-use
    def run(self):
        ''' run command '''
        print("Unsupported command for openshift-ansible")


setup(
    name='openshift-ansible',
    license="Apache 2.0",
    cmdclass={
        'install': UnsupportedCommand,
        'develop': UnsupportedCommand,
        'build': UnsupportedCommand,
        'build_py': UnsupportedCommand,
        'build_ext': UnsupportedCommand,
        'egg_info': UnsupportedCommand,
        'sdist': UnsupportedCommand,
        'lint': OpenShiftAnsiblePylint,
        'yamllint': OpenShiftAnsibleYamlLint,
        'generate_validation': OpenShiftAnsibleGenerateValidation,
        'ansible_syntax': OpenShiftAnsibleSyntaxCheck,
    },
    packages=[],
)
