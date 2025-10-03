# Contributing to WhirlTube

Thank you for your interest in contributing to WhirlTube! This project aims to be a lean, native YouTube client for GNOME/Wayland using MPV + yt-dlp. Small, focused PRs are very welcome.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Coding Style](#coding-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)

## Code of Conduct
This project and everyone participating in it is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How Can I Contribute?

### Reporting Bugs
Before creating bug reports, please check the issues list as you might find an existing one. When you create a bug report, provide detailed information to help us reproduce and fix the issue.

### Suggesting Enhancements
Enhancement suggestions are welcome, especially for features that align with the project's goals. Create an issue with the `enhancement` tag to discuss your idea before implementing it.

### Your First Code Contribution
- Look for issues tagged with `good first issue`
- Fork the repository and create your branch from `master`
- Follow the development setup and coding guidelines below

## Development Setup

### System Dependencies
First, install the required system dependencies based on your distribution:

**Arch Linux:**
```bash
sudo pacman -S --needed gtk4 libadwaita python-gobject mpv ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libmpv-dev mpv ffmpeg
```

**Fedora:**
```bash
sudo dnf install python3-gobject gtk4-devel libadwaita-devel mpv-libs mpv ffmpeg
```

### Python Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e .[dev]
```

### Running the Application
```bash
WHIRLTUBE_DEBUG=1 whirltube
# Or for development builds
WHIRLTUBE_DEBUG=1 python -m whirltube
```

## Coding Style

### Python Style Guide
- Follow PEP 8 style guide with Ruff linting
- Use type hints for all function parameters and return values
- Write docstrings for all public classes, functions, and modules
- Keep functions small and focused on a single responsibility
- Limit lines to 88 characters (enforced by Ruff)
- Use meaningful variable and function names

### Commit Messages
- Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `build:`
- Write commit messages in the imperative mood ("Add feature" not "Added feature")
- Keep commits focused: one logical change per commit

### File Structure
- Place UI components in `src/whirltube/ui/`
- Place business logic in `src/whirltube/services/`
- Place data models in `src/whirltube/models/`
- Place external API providers in `src/whirltube/providers/`

## Testing

### Running Tests
```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=src/whirltube

# Run specific test file
python -m pytest tests/test_filename.py
```

### Test Guidelines
- Write tests for all new features and bug fixes
- Focus on testing parsers (ytdlp_runner), options mapping (dialogs), and provider helpers
- Test edge cases and error conditions
- Aim for high code coverage, especially for critical paths

## Pull Request Process

### Before Submitting
1. Ensure all tests pass: `python -m pytest tests/`
2. Run linting: `ruff check .`
3. Run type checking: `mypy .`
4. Verify the build: `bash scripts/build_and_verify.sh`
5. Update documentation as needed

### PR Checklist
- [ ] All tests pass
- [ ] Linting passes (Ruff)
- [ ] Type checking passes (mypy)
- [ ] Build verification passes locally
- [ ] No stray files (e.g., *.bak)
- [ ] Clear description with issue links if applicable
- [ ] Appropriate labels applied
- [ ] PR title follows conventional commit format

### PR Review Process
- PRs should have descriptive titles and descriptions
- PRs must pass all CI checks before review
- At least one maintainer review is required before merging
- Maintain good commit history: avoid unnecessary merge commits

## Reporting Issues

Use the issue templates when creating bug reports or feature requests. Include as much detail as possible:
- OS and distribution
- Python version
- WhirlTube version
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Debug logs when applicable (`WHIRLTUBE_DEBUG=1`)

## Development Workflow

### Feature Branches
- Create feature branches from `master`: `git checkout -b feature/description`
- Keep feature branches focused on a single enhancement or bug fix
- Rebase frequently to keep up with `master`: `git rebase master`

### Code Reviews
- Be open to feedback and suggestions
- Make requested changes promptly
- Explain the reasoning behind your implementation choices

## Project Structure

```
whirltube/
├── src/
│   └── whirltube/          # Main application source
│       ├── ui/             # User interface components
│       ├── services/       # Business logic services
│       ├── models/         # Data models
│       ├── providers/      # YouTube provider implementations
│       ├── __init__.py     # Package entry point
│       └── window.py       # Main window implementation
├── tests/                  # Test files
├── scripts/                # Development and build scripts
├── data/                   # Application data files
├── flatpak/                # Flatpak build files
├── .github/                # GitHub configuration
│   ├── workflows/          # CI/CD workflows
│   └── ISSUE_TEMPLATE/     # Issue templates
├── pyproject.toml          # Python package configuration
└── README.md               # Project documentation
```

## Getting Help

If you have questions about contributing:
- Open an issue with the `question` label
- Check existing documentation
- Review closed pull requests for examples of previous contributions

Thank you for contributing to WhirlTube!