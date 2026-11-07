"""Language inventory shared by scanning and conservative adapters."""
from pathlib import Path

LANGUAGES = {
    'sas': ('.sas',), 'sql': ('.sql', '.ddl', '.dml'), 'python': ('.py',),
    'shell': ('.sh', '.bash', '.zsh'), 'javascript': ('.js', '.jsx', '.mjs', '.cjs'),
    'typescript': ('.ts', '.tsx', '.mts', '.cts'), 'java': ('.java',),
    'kotlin': ('.kt', '.kts'), 'scala': ('.scala',), 'go': ('.go',),
    'rust': ('.rs',), 'csharp': ('.cs',), 'ruby': ('.rb',), 'r': ('.r',),
    'c': ('.c', '.h'), 'cpp': ('.cpp', '.hpp', '.cc'), 'php': ('.php',),
}
SOURCE_SUFFIXES = {suffix for suffixes in LANGUAGES.values() for suffix in suffixes}
MANIFESTS = {'package.json', 'pyproject.toml', 'setup.py', 'Cargo.toml', 'go.mod',
             'pom.xml', 'build.gradle', 'build.gradle.kts', 'Gemfile', 'composer.json',
             'pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'turbo.json'}


def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return next((name for name, suffixes in LANGUAGES.items() if suffix in suffixes), 'configuration')
