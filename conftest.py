# 让 pytest 无论从哪里启动，都能 import 项目根下的包（core/data/huntzone/pages）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
