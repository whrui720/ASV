#!/usr/bin/env python3
"""
Test runner script for hybrid_citation_scraper test suite.

Usage:
    python scripts/run_tests.py              # Run all tests
    python scripts/run_tests.py --coverage   # Run with coverage report
    python scripts/run_tests.py --verbose    # Run with verbose output
    python scripts/run_tests.py --fast       # Skip slow tests
    python scripts/run_tests.py --module utils  # Test specific module
"""

import sys
import subprocess
import argparse
from pathlib import Path


def main():
    """Main test runner function"""
        repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Run tests for hybrid_citation_scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/run_tests.py --coverage          # Full test with coverage
    python scripts/run_tests.py --module utils      # Test utils module only
    python scripts/run_tests.py --verbose --fast    # Verbose output, skip slow tests
        """
    )
    
    parser.add_argument(
        '--coverage', '-c',
        action='store_true',
        help='Run tests with coverage report'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose test output'
    )
    
    parser.add_argument(
        '--fast', '-f',
        action='store_true',
        help='Skip slow tests'
    )
    
    parser.add_argument(
        '--module', '-m',
        type=str,
        help='Test specific module (utils, llm_client, claim_extractor, config)'
    )
    
    parser.add_argument(
        '--html-report',
        action='store_true',
        help='Generate HTML coverage report'
    )
    
    parser.add_argument(
        '--markers',
        type=str,
        help='Run tests matching specific markers (e.g., "unit", "integration")'
    )
    
    parser.add_argument(
        '--parallel', '-n',
        type=int,
        metavar='NUM',
        help='Run tests in parallel with NUM workers (requires pytest-xdist)'
    )
    
    args = parser.parse_args()
    
    # Build pytest command
    cmd = ['pytest']
    
    # Add verbosity
    if args.verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    # Add coverage
    if args.coverage:
        cmd.extend([
            '--cov=hybrid_citation_scraper',
            '--cov-report=term-missing'
        ])
        
        if args.html_report:
            cmd.append('--cov-report=html')
    
    # Add marker filtering
    if args.fast:
        cmd.extend(['-m', 'not slow'])
    
    if args.markers:
        cmd.extend(['-m', args.markers])
    
    # Add parallel execution
    if args.parallel:
        cmd.extend(['-n', str(args.parallel)])
    
    # Add specific module
    if args.module:
        test_file = f'hybrid_citation_scraper/tests/test_{args.module}.py'
        if not (repo_root / test_file).exists():
            print(f"Error: Test file not found: {test_file}")
            print(f"Available modules: utils, llm_client, claim_extractor, config")
            return 1
        cmd.append(test_file)
    else:
        cmd.append('hybrid_citation_scraper/tests/')
    
    # Print command
    print(f"Running: {' '.join(cmd)}")
    print("-" * 60)
    
    # Run pytest
    try:
        result = subprocess.run(cmd, check=False, cwd=repo_root)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        return 130
    except Exception as e:
        print(f"\nError running tests: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
