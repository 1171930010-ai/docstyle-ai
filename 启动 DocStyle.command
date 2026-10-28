#!/bin/zsh
function task_fail() {
  print -u2 -- "启动停止：$1"
  print -u2 '请拍下本窗口从“失败步骤”到末尾的内容，用于定位客户电脑的问题。'
  if [[ -t 0 ]]; then read -r '?按回车关闭。'; fi
  exit 1
}
function task_permission_help() {
  print '若上方出现 Operation not permitted，请检查：'
  print '系统设置 → 隐私与安全 → 文件和文件夹 → 终端 → 当前所在文件夹的访问权限。'
  print '若项目在“下载”中，请检查“下载文件夹”；改动后完全退出终端并重新启动。'
  print '该错误也可能来自 Python 安装或环境中的其他文件权限，请保留上方具体路径。'
}
print 'DocStyle 启动诊断版 · 2026-10-26'
cd "${0:A:h}" || task_fail '失败步骤：进入项目文件夹。请检查终端对该文件夹的访问权限。'
[[ -r server.py && -r requirements.txt ]] || task_fail '失败步骤：读取项目文件。请把此启动文件放回完整的 DocStyle_AI_v5 文件夹内。'
print 'DocStyle AI · 启动工作台'
print '[1/3] 检查本机 Python 环境…' 
if [[ ! -x .venv/bin/python ]]; then
  typeset task_python_path=''
  typeset -a task_python_candidates
  task_python_candidates=("/opt/homebrew/bin/python3" "/usr/local/bin/python3" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" "python3")
  for task_python_candidate in "${task_python_candidates[@]}"; do
    if "$task_python_candidate" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
      task_python_path="$task_python_candidate"
      break
    fi
  done
  if [[ -z "$task_python_path" ]]; then
    task_fail '失败步骤：寻找 Python。请安装 Python 3.10 或更新版本（推荐 3.12），再重新双击。'
  fi
  print '正在首次创建本机运行环境…'
  if ! "$task_python_path" - <<'PY'
import sys
import traceback
import venv
print('使用的 Python：' + sys.executable, flush=True)
print('Python 版本：' + sys.version.split()[0], flush=True)
try:
    venv.EnvBuilder(with_pip=True, symlinks=True).create('.venv')
except Exception:
    print('失败步骤：创建 Python 运行环境（.venv）', file=sys.stderr, flush=True)
    traceback.print_exc()
    sys.exit(1)
PY
  then
    task_permission_help
    task_fail '创建本机运行环境失败；尚未启动网页服务。'
  fi
fi
if ! .venv/bin/python -c 'import sys; print("运行环境 Python：" + sys.executable, flush=True); assert sys.version_info >= (3,10)'; then
  task_permission_help
  task_fail '失败步骤：运行已有 .venv。复制自另一台电脑的环境可能不可用，请保留报错，由支持人员确认重建。'
fi
print '[2/3] 检查排版组件…'
if ! .venv/bin/python -c 'import lxml,docx,latex2mathml,mathml2omml,pdfplumber,pypdfium2,reportlab,PIL' 2>/dev/null; then
  print '首次配置需要安装组件，请等待；安装失败时请保留最后几行提示。'
  .venv/bin/python -m pip install -r requirements.txt || task_fail '失败步骤：安装排版组件。请保留上方下载、网络或权限错误。'
fi
print '[3/3] 启动服务并打开浏览器…'
print '工作台地址：http://127.0.0.1:8770'
.venv/bin/python server.py --port 8770 --open
task_start_status=$?
if (( task_start_status != 0 )); then
  task_fail '失败步骤：运行网页服务。请保留上方错误信息。'
fi
exit $task_start_status
