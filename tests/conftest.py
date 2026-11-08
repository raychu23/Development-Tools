"""tests import the CLIs from ../systems (they sit side by side in the private workspace)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'systems'))
