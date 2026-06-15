"""
个人周报助手 —— Gradio 主界面
"""

import json, logging
from datetime import date, datetime, timedelta
from pathlib import Path

import gradio as gr
from sqlalchemy.orm import joinedload

from models import init_db, get_session, Project, Task, NextWeekPlan, Setting
from services.project import list_projects, create_project, update_project, delete_project
from services.task import (
    create_task, update_task, complete_task, undo_complete_task,
    delete_task, get_task, get_tasks_by_week, get_completed_tasks_by_week,
    get_week_total_hours, get_tasks_grouped_by_project, get_all_tasks, validate_hours,
)
from services.plan import (
    create_plan, update_plan, delete_plan,
    get_plans_by_target_week, get_plans_grouped_by_project,
    sync_plans_to_tasks, count_unsynced_plans_for_week, get_default_next_week,
)
from services.report import generate_weekly_report, generate_weekly_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("data/app.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("app")
init_db()


def _s(): return get_session()
def _default_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=4)
def _parse(s):
    if not s: return None
    try: return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError: return None
def _fmt(d): return d.strftime("%Y-%m-%d")
def _proj_choices():
    s = _s()
    try: return [p.name for p in list_projects(s)]
    finally: s.close()
def _proj_id(name):
    from services.project import get_project_by_name
    s = _s()
    try:
        p = get_project_by_name(s, name)
        return p.id if p else None
    finally: s.close()
def _default_total_hours():
    s = _s()
    try:
        r = s.query(Setting).filter(Setting.key == "total_hours_per_week").first()
        return float(r.value) if r else 40.0
    finally: s.close()


# ═══════════════════════════ CSS & JS ═══════════════════════════
TREE_CSS = """<style>
.tree { font-family: 'Times New Roman', Times, 'Songti SC', 'Noto Serif SC', serif; font-size: 14px; }
.tree details { margin: 2px 0; }
.tree details > summary { list-style: none; cursor: pointer; padding: 6px 8px; border-radius: 4px; user-select: none; display: flex; align-items: center; gap: 4px; }
.tree details > summary:hover { background: #f0f0f0; }
.tree details > summary::-webkit-details-marker { display: none; }
.tree .proj-summary { font-weight: 600; background: #f8f8f8; }
.tree .proj-summary:hover { background: #ececec; }
.tree .task-row { display: flex; align-items: center; padding: 4px 8px; margin: 1px 0; border-radius: 4px; gap: 6px; }
.tree .task-row:hover { background: #f5f5f5; }
.tree .task-row.done .task-name { text-decoration: line-through; color: #999; }
.tree .task-name { flex: 1; }
.tree .task-hours { color: #666; font-size: 12px; min-width: 40px; text-align: right; }
.tree .task-actions { display: flex; gap: 2px; opacity: 0; transition: opacity 0.1s; }
.tree .task-row:hover .task-actions, .tree details > summary:hover .task-actions { opacity: 1; }
.tree .task-actions button, .tree details > summary .task-actions button { background: none; border: 1px solid #ddd; border-radius: 3px; cursor: pointer; font-size: 12px; padding: 1px 6px; }
.tree .task-actions button:hover, .tree details > summary .task-actions button:hover { background: #e8e8e8; }
.tree .plan-badge { font-size: 10px; color: #888; margin-left: 4px; }
.tree input[type=checkbox] { width: 15px; height: 15px; cursor: pointer; accent-color: #4caf50; }
.tree .edit-input { font-size: 13px; padding: 2px 4px; border: 1px solid #4caf50; border-radius: 3px; width: 120px; }
.tree .edit-input-hours { width: 50px; }
.tree .add-form { margin: 4px 0 4px 32px; display: flex; gap: 6px; align-items: center; }
.tree .add-form input { font-size: 13px; padding: 3px 6px; border: 1px solid #4caf50; border-radius: 3px; }
.tree .add-form button { font-size: 12px; padding: 3px 8px; border: 1px solid #ccc; border-radius: 3px; cursor: pointer; background: #f8f8f8; }
.tree .add-form button:hover { background: #e8e8e8; }
</style>"""

TREE_JS = """
function sendCmd(action, payload) {
    var cmdBox = document.getElementById('js_cmd_box');
    var trigger = document.getElementById('js_trigger');
    if (!cmdBox || !trigger) { console.error('Channel not found'); return; }
    var inner = cmdBox.querySelector('textarea') || cmdBox.querySelector('input');
    if (!inner) { console.error('Textarea not found'); return; }
    inner.value = JSON.stringify({action: action, payload: payload});
    inner.dispatchEvent(new Event('input', { bubbles: true }));
    setTimeout(function() {
        if (trigger.tagName === 'BUTTON') trigger.click();
        else { var b = trigger.querySelector('button'); if (b) b.click(); }
    }, 80);
}
function toggleTask(taskId, checked) {
    sendCmd('toggle_' + (checked ? 'complete' : 'undo'), {task_id: taskId});
}
function confirmDelete(type, id, name) {
    var msg = '确定删除 "' + name + '" ？';
    if (type === 'project_tasks') msg += '\\n（仅删除当前周任务，项目本身保留）';
    else if (type === 'project_plans') msg += '\\n（仅删除当前目标周计划，项目本身保留）';
    else if (type === 'project') msg += ' 将删除该项目及所有任务。';
    else msg += ' 将删除该任务及其所有子任务。';
    if (confirm(msg)) sendCmd('delete_' + type, {id: id});
}
function startEdit(type, id, field) {
    var span = document.getElementById(field + '_' + type + '_' + id);
    if (!span) return;
    var current = span.textContent.trim();
    var input = document.createElement('input');
    input.type = 'text'; input.value = current;
    input.className = 'edit-input' + (field === 'hours' ? ' edit-input-hours' : '');
    span.replaceWith(input); input.focus(); input.select();
    var save = function() {
        var newVal = input.value.trim();
        if (newVal && newVal !== current) sendCmd('edit_' + field, {type: type, id: id, value: newVal});
        else { var ns = document.createElement('span'); ns.id = field + '_' + type + '_' + id; ns.textContent = current; ns.className = span.className; input.replaceWith(ns); }
    };
    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); save(); } });
}
function startEditHours(type, id) { startEdit(type, id, 'hours'); }
function toggleAddForm(parentType, parentId) {
    var form = document.getElementById('add_form_' + parentType + '_' + parentId);
    if (!form) return;
    if (form.style.display === 'none' || !form.style.display) {
        form.style.display = 'flex';
        var ni = form.querySelector('.add-name'); if (ni) { ni.focus(); ni.value = ''; }
        var hi = form.querySelector('.add-hours'); if (hi) hi.value = '2.0';
    } else { form.style.display = 'none'; }
}
function submitAddSubtask(parentType, parentId) {
    var form = document.getElementById('add_form_' + parentType + '_' + parentId);
    if (!form) return;
    var ni = form.querySelector('.add-name'); var hi = form.querySelector('.add-hours');
    var name = ni ? ni.value.trim() : ''; var hours = hi ? hi.value : '0';
    if (!name) { alert('请输入任务名称'); return; }
    sendCmd('add_subtask', {parent_type: parentType, parent_id: parentId, name: name, hours: parseFloat(hours) || 0});
    form.style.display = 'none';
}
"""


# ═══════════════════════════ 树渲染 ═══════════════════════════
def _render_task_node(task, indent=12):
    """递归渲染一个任务及其所有子任务"""
    parts = []
    tid = task.id
    checked = 'checked' if task.status == 'completed' else ''
    done_class = 'done' if task.status == 'completed' else ''
    hours_str = f"{task.hours}h" if task.hours is not None else "-"
    desc = task.description.replace("'", "\\'").replace('"', '&quot;')

    # 加载子任务（如果未预加载）
    children = sorted(task.children, key=lambda c: c.created_at or datetime.min) if task.children else []
    active_children = [c for c in children if not c.is_deleted]
    has_children = len(active_children) > 0

    if has_children:
        # 父任务：用 details/summary 包裹，不显示复选框
        parts.append(f'<details open style="margin-left:{indent}px">')
        parts.append(
            f'<summary style="list-style:none;cursor:pointer;padding:4px 8px;border-radius:4px;display:flex;align-items:center;gap:4px">'
            f'<span style="font-size:10px;width:14px;color:#888">▶</span>'
            f'<span class="task-name" id="name_task_{tid}" style="font-weight:500">{desc}</span>'
            f'<span class="task-hours" id="hours_task_{tid}" style="cursor:pointer" '
            f'onclick="event.stopPropagation();startEditHours(\'task\',{tid})" title="修改工时">{hours_str}</span>'
            f'<span class="task-actions" style="margin-left:auto">'
            f'<button onclick="event.stopPropagation();toggleAddForm(\'task\',{tid})" title="新增子任务">+子</button>'
            f'<button onclick="event.stopPropagation();startEdit(\'task\',{tid},\'name\')" title="编辑">✏</button>'
            f'<button onclick="event.stopPropagation();confirmDelete(\'task\',{tid},\'{desc[:20]}\')" title="删除">🗑</button>'
            f'</span></summary>'
        )
        parts.append(
            f'<div class="add-form" id="add_form_task_{tid}" style="display:none;margin-left:{indent+20}px">'
            f'<input class="add-name" placeholder="子任务名称" style="width:180px">'
            f'<input class="add-hours" type="number" step="0.5" min="0" value="2.0" style="width:60px" title="工时(h)">'
            f'<button onclick="submitAddSubtask(\'task\',{tid})">添加</button>'
            f'<button onclick="toggleAddForm(\'task\',{tid})">取消</button></div>'
        )
        for child in active_children:
            parts.append(_render_task_node(child, indent + 20))
        parts.append('</details>')
    else:
        # 叶子任务：显示复选框
        parts.append(
            f'<div class="task-row {done_class}" id="row_task_{tid}" style="margin-left:{indent}px">'
            f'<input type="checkbox" id="cb_task_{tid}" {checked} '
            f'onchange="toggleTask({tid}, this.checked)">'
            f'<span class="task-name" id="name_task_{tid}">{desc}</span>'
            f'<span class="task-hours" id="hours_task_{tid}" style="cursor:pointer" '
            f'onclick="startEditHours(\'task\',{tid})" title="修改工时">{hours_str}</span>'
            f'<span class="task-actions">'
            f'<button onclick="toggleAddForm(\'task\',{tid})" title="新增子任务">+子</button>'
            f'<button onclick="startEdit(\'task\',{tid},\'name\')" title="编辑">✏</button>'
            f'<button onclick="confirmDelete(\'task\',{tid},\'{desc[:20]}\')" title="删除">🗑</button>'
            f'</span>'
            f'<div class="add-form" id="add_form_task_{tid}" style="display:none">'
            f'<input class="add-name" placeholder="子任务名称" style="width:180px">'
            f'<input class="add-hours" type="number" step="0.5" min="0" value="2.0" style="width:60px" title="工时(h)">'
            f'<button onclick="submitAddSubtask(\'task\',{tid})">添加</button>'
            f'<button onclick="toggleAddForm(\'task\',{tid})">取消</button></div>'
            f'</div>'
        )
    return "".join(parts)


def _render_current_week_tree(ws, we):
    """渲染本周任务树（支持 task.parent_id 嵌套）"""
    s = _s()
    try:
        all_tasks = s.query(Task).filter(
            Task.week_start == ws, Task.week_end == we, Task.is_deleted == False,
        ).options(joinedload(Task.project), joinedload(Task.children)).order_by(Task.created_at.asc()).all()
    finally:
        s.close()

    # 按项目分组，只统计叶子任务工时（避免父子重复计算）
    proj_map = {}
    for t in all_tasks:
        pid = t.project_id
        if pid not in proj_map:
            proj_map[pid] = {"project": t.project, "tasks": [], "total_hours": 0.0}
        proj_map[pid]["tasks"].append(t)
        # 只统计叶子任务（无未删除子任务）的工时
        active_children = [c for c in (t.children or []) if not c.is_deleted]
        if not active_children and t.hours:
            proj_map[pid]["total_hours"] += t.hours

    if not proj_map:
        return TREE_CSS + '<div class="tree"><div style="color:#888;padding:20px;text-align:center">本周暂无任务</div></div>'

    parts = [TREE_CSS, '<div class="tree">']
    for g in proj_map.values():
        proj, all_t, total_h = g["project"], g["tasks"], round(g["total_hours"], 1)
        pid = proj.id
        top_tasks = [t for t in all_t if t.parent_id is None]
        pname = proj.name.replace("'", "\\'")

        parts.append('<details open>')
        parts.append(
            f'<summary class="proj-summary">'
            f'<span id="name_project_{pid}">📁 {proj.name}</span>'
            f' <span id="hours_project_{pid}" style="color:#666;font-size:12px">({total_h}h)</span>'
            f'<span class="task-actions" style="margin-left:auto;opacity:1">'
            f'<button onclick="toggleAddForm(\'project\',{pid})" title="新增顶层任务">+</button>'
            f'<button onclick="confirmDelete(\'project_tasks\',{pid},\'{pname} 的本周任务\')" title="删除本周该项目下所有任务">🗑</button>'
            f'</span></summary>'
        )
        parts.append(
            f'<div class="add-form" id="add_form_project_{pid}" style="display:none">'
            f'<input class="add-name" placeholder="任务名称" style="width:200px">'
            f'<input class="add-hours" type="number" step="0.5" min="0" value="2.0" style="width:60px" title="工时(h)">'
            f'<button onclick="submitAddSubtask(\'project\',{pid})">添加</button>'
            f'<button onclick="toggleAddForm(\'project\',{pid})">取消</button></div>'
        )
        for t in top_tasks:
            parts.append(_render_task_node(t, indent=12))
        parts.append('</details>')
    parts.append('</div>')
    return "".join(parts)


def _render_plan_tree(pws, pwe):
    """渲染下周计划树"""
    s = _s()
    try:
        grouped = get_plans_grouped_by_project(s, pws, pwe)
    finally:
        s.close()
    if not grouped:
        return TREE_CSS + '<div class="tree"><div style="color:#888;padding:20px;text-align:center">暂无计划</div></div>'
    parts = [TREE_CSS, '<div class="tree">']
    for g in grouped.values():
        proj, plans = g["project"], g["plans"]
        pid = proj.id
        pname = proj.name.replace("'", "\\'")
        parts.append('<details open>')
        parts.append(
            f'<summary class="proj-summary" style="background:#fafafa">'
            f'<span id="name_project_{pid}">📁 {proj.name}</span>'
            f' <span style="color:#999;font-size:11px">📅 计划</span>'
            f'<span class="task-actions" style="margin-left:auto;opacity:1">'
            f'<button onclick="toggleAddForm(\'project\',{pid})" title="新增计划">+</button>'
            f'<button onclick="confirmDelete(\'project_plans\',{pid},\'{pname} 的当前计划\')" title="删除当前计划周该项目下所有计划">🗑</button>'
            f'</span></summary>'
        )
        parts.append(
            f'<div class="add-form" id="add_form_project_{pid}" style="display:none">'
            f'<input class="add-name" placeholder="计划名称" style="width:250px">'
            f'<button onclick="submitAddSubtask(\'project\',{pid})">添加</button>'
            f'<button onclick="toggleAddForm(\'project\',{pid})">取消</button></div>'
        )
        for p in plans:
            badge = ' <span class="plan-badge">✓已同步</span>' if p.is_synced else ''
            pdesc = p.description[:20].replace("'", "\\'")
            parts.append(
                f'<div class="task-row" id="row_plan_{p.id}" style="margin-left:12px">'
                f'<span style="width:15px"></span>'
                f'<span class="task-name" id="name_plan_{p.id}">○ {p.description}{badge}</span>'
                f'<span class="task-actions">'
                f'<button onclick="startEdit(\'plan\',{p.id},\'name\')" title="编辑">✏</button>'
                f'<button onclick="confirmDelete(\'plan\',{p.id},\'{pdesc}\')" title="删除">🗑</button>'
                f'</span></div>'
            )
        parts.append('</details>')
    parts.append('</div>')
    return "".join(parts)


# ═══════════════════════════ 构建应用 ═══════════════════════════
def build_app():
    dws, dwe = _default_week()
    dpws, dpwe = get_default_next_week()
    head_html = f"<style>#js_cmd_box,#js_trigger{{position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none}}</style><script>{TREE_JS}</script>"

    with gr.Blocks(title="个人周报助手", theme=gr.themes.Soft(), head=head_html,
                   css="""
                   * { font-family: 'Times New Roman', Times, 'Songti SC', 'Noto Serif SC', serif !important; }
                   .warning-box{background:#fff3cd;border:1px solid #ffc107;color:#856404;padding:8px 12px;border-radius:4px;margin:8px 0}
                   """) as app:

        ws_state = gr.State(dws)
        we_state = gr.State(dwe)
        pws_state = gr.State(dpws)
        pwe_state = gr.State(dpwe)
        custom_h_state = gr.State(None)
        tab_state = gr.State("current")

        gr.Markdown("# 📊 个人周报助手")

        # ═══════════════ Tab 1: 任务看板 ═══════════════
        with gr.TabItem("🏠 任务看板"):
            with gr.Row():
                ws_tb = gr.Textbox(label="起始日期", value=_fmt(dws), scale=2)
                we_tb = gr.Textbox(label="结束日期", value=_fmt(dwe), scale=2)
                switch_btn = gr.Button("切换周期", scale=1, variant="secondary")
            sync_tip = gr.Markdown("")

            with gr.Row():
                tab_current_btn = gr.Button("📋 本周任务", variant="primary", scale=1)
                tab_plan_btn = gr.Button("📅 下周计划", variant="secondary", scale=1)

            hours_md = gr.Markdown("")
            warning_md = gr.Markdown("")

            with gr.Row():
                custom_h_num = gr.Number(label="自定义总工时（留空=默认40h）", value=None, precision=1, minimum=0, step=0.5, scale=3)
                apply_h_btn = gr.Button("应用", scale=1, variant="secondary")

            with gr.Accordion("➕ 新增任务", open=False):
                with gr.Row():
                    add_proj_dd = gr.Dropdown(label="项目", choices=_proj_choices(), scale=2, interactive=True)
                    add_name_tb = gr.Textbox(label="任务描述", scale=3)
                    add_hours_num = gr.Number(label="工时(h)", value=2.0, precision=1, minimum=0, step=0.5, scale=1)
                    add_btn = gr.Button("添加", scale=1, variant="primary")
                add_msg = gr.Markdown("")

            with gr.Row(visible=False) as plan_week_row:
                plan_ws_tb = gr.Textbox(label="目标周起始", value=_fmt(dpws), scale=2)
                plan_we_tb = gr.Textbox(label="目标周结束", value=_fmt(dpwe), scale=2)
                apply_plan_week_btn = gr.Button("应用目标周", scale=1, variant="secondary")
            plan_week_msg = gr.Markdown("")

            with gr.Row(visible=False) as sync_row:
                sync_btn = gr.Button("⬇ 同步计划到本周任务", variant="secondary")
                sync_msg = gr.Markdown("")

            tree_html = gr.HTML("")
            js_cmd = gr.Textbox(visible=True, elem_id="js_cmd_box")
            js_trigger = gr.Button(".", visible=True, elem_id="js_trigger")

            gr.Markdown("---")
            gr.Markdown("### 📝 生成周报")
            report_btn = gr.Button("🤖 生成周报", variant="primary")
            report_out = gr.Textbox(label="周报内容", lines=10, max_lines=25, interactive=False)
            report_msg = gr.Markdown("")

        # ═══════════════ Tab 2: 历史任务 ═══════════════
        with gr.TabItem("📋 历史任务"):
            with gr.Row():
                h_ws_tb = gr.Textbox(label="周起始", placeholder="2026-01-01", scale=2)
                h_we_tb = gr.Textbox(label="周结束", placeholder="2026-12-31", scale=2)
                h_proj_dd = gr.Dropdown(label="项目", choices=[""] + _proj_choices(), scale=2)
                h_status_dd = gr.Dropdown(label="状态", choices=["全部", "pending", "completed"], value="全部", scale=1)
                h_kw_tb = gr.Textbox(label="关键词", scale=2)
                h_search_btn = gr.Button("查询", scale=1, variant="primary")
            hist_html = gr.HTML("")

        # ═══════════════ Tab 3: 设置 ═══════════════
        with gr.TabItem("⚙ 设置"):
            gr.Markdown("### 项目管理")
            proj_table_html = gr.HTML("")
            with gr.Row():
                new_proj_tb = gr.Textbox(label="新建项目名称", scale=3)
                create_proj_btn = gr.Button("+ 创建", scale=1, variant="primary")
            with gr.Row():
                rename_proj_dd = gr.Dropdown(label="选择项目", choices=_proj_choices(), scale=3)
                rename_proj_tb = gr.Textbox(label="新名称", scale=3)
                rename_proj_btn = gr.Button("✎ 重命名", scale=1, variant="secondary")
            with gr.Row():
                del_proj_dd = gr.Dropdown(label="选择项目", choices=_proj_choices(), scale=3)
                del_proj_btn = gr.Button("🗑 删除", scale=1, variant="stop")
            proj_msg = gr.Markdown("")
            gr.Markdown("### 默认设置")
            with gr.Row():
                default_h_num = gr.Number(label="每周默认总工时", value=_default_total_hours(), precision=1, minimum=0, step=0.5, scale=2)
                save_set_btn = gr.Button("💾 保存", scale=1, variant="primary")
            set_msg = gr.Markdown("")
            db_path = Path("data/todo.db")
            gr.Markdown(f"数据库: `{db_path.absolute()}` | 大小: {db_path.stat().st_size / 1024:.0f} KB" if db_path.exists() else "数据库: 未创建")

        # ═══════════════ 刷新函数 ═══════════════
        def refresh_tree(ws_d, we_d, pws_d, pwe_d, custom_h, active_tab):
            if not all([ws_d, we_d, pws_d, pwe_d]):
                return "", "", "", gr.update(), gr.update()
            default_h = _default_total_hours()
            total_h = custom_h if custom_h is not None else default_h
            pc = _proj_choices()
            if active_tab == "current":
                s = _s()
                try: allocated = get_week_total_hours(s, ws_d, we_d)
                finally: s.close()
                remaining = round(total_h - allocated, 1)
                hours_text = f"总工时: **{total_h}h** | 已分配: **{allocated}h** | 剩余: **{remaining}h**"
                warning = f'<div class="warning-box">⚠ 已超工时 **{abs(remaining)}h**，超出 {total_h}h</div>' if remaining < 0 else ""
                tree = _render_current_week_tree(ws_d, we_d)
            else:
                hours_text = f"📅 下周计划 | 总工时: **{total_h}h**（计划阶段不统计工时）"
                warning = ""
                tree = _render_plan_tree(pws_d, pwe_d)
            return tree, hours_text, warning, gr.update(choices=pc, value=None), gr.update(choices=pc, value=None)

        TREE_OUT = [tree_html, hours_md, warning_md, add_proj_dd, add_proj_dd]
        FULL_IN = [ws_state, we_state, pws_state, pwe_state, custom_h_state, tab_state]

        # ═══════════════ 事件绑定 ═══════════════
        def switch_to_current():
            return "current", gr.update(variant="primary"), gr.update(variant="secondary"), gr.update(visible=False), gr.update(visible=False)
        def switch_to_plan():
            return "plan", gr.update(variant="secondary"), gr.update(variant="primary"), gr.update(visible=True), gr.update(visible=True)

        tab_current_btn.click(switch_to_current, outputs=[tab_state, tab_current_btn, tab_plan_btn, plan_week_row, sync_row]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)
        tab_plan_btn.click(switch_to_plan, outputs=[tab_state, tab_current_btn, tab_plan_btn, plan_week_row, sync_row]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_switch(ws_s, we_s):
            ws = _parse(ws_s); we = _parse(we_s)
            if not ws or not we: return ws_s, we_s, _fmt(get_default_next_week()[0]), _fmt(get_default_next_week()[1]), None, ""
            nws = ws + timedelta(days=7); nwe = we + timedelta(days=7)
            return _fmt(ws), _fmt(we), _fmt(nws), _fmt(nwe), None, ""
        switch_btn.click(handle_switch, inputs=[ws_tb, we_tb], outputs=[ws_tb, we_tb, plan_ws_tb, plan_we_tb, custom_h_state, sync_tip]).then(
            lambda ws_s, we_s, pws_s, pwe_s: (_parse(ws_s), _parse(we_s), _parse(pws_s), _parse(pwe_s)),
            inputs=[ws_tb, we_tb, plan_ws_tb, plan_we_tb], outputs=[ws_state, we_state, pws_state, pwe_state],
        ).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        apply_h_btn.click(lambda v: v if v and v > 0 else None, inputs=[custom_h_num], outputs=[custom_h_state]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_apply_plan_week(pws_s, pwe_s):
            pws = _parse(pws_s); pwe = _parse(pwe_s)
            if not pws or not pwe: return pws_s, pwe_s, "❌ 日期格式错误"
            return _fmt(pws), _fmt(pwe), ""
        apply_plan_week_btn.click(handle_apply_plan_week, inputs=[plan_ws_tb, plan_we_tb], outputs=[plan_ws_tb, plan_we_tb, plan_week_msg]).then(
            lambda pws_s, pwe_s: (_parse(pws_s), _parse(pwe_s)), inputs=[plan_ws_tb, plan_we_tb], outputs=[pws_state, pwe_state],
        ).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_sync(ws_d, we_d):
            s = _s()
            try: cnt = sync_plans_to_tasks(s, ws_d, we_d); return f"✅ 已同步 {cnt} 条计划"
            except ValueError as e: return f"❌ {e}"
            finally: s.close()
        sync_btn.click(handle_sync, inputs=[ws_state, we_state], outputs=[sync_msg]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        # ── JS 命令处理 ──
        def handle_js_command(cmd_json, ws_d, we_d, pws_d, pwe_d, custom_h, active_tab):
            if not cmd_json: return ""
            try: cmd = json.loads(cmd_json)
            except: return ""
            action = cmd.get("action", ""); payload = cmd.get("payload", {})
            s = _s()
            try:
                if action == "toggle_complete": complete_task(s, payload["task_id"])
                elif action == "toggle_undo": undo_complete_task(s, payload["task_id"])
                elif action == "delete_project_tasks":
                    # 仅删除当前周该项目下所有任务，不删项目本身
                    tasks = s.query(Task).filter(
                        Task.project_id == payload["id"],
                        Task.week_start == ws_d, Task.week_end == we_d,
                        Task.is_deleted == False, Task.parent_id == None,
                    ).all()
                    for t in tasks:
                        delete_task(s, t.id)  # 级联软删除子任务
                elif action == "delete_project_plans":
                    # 仅删除目标周该项目下所有计划，不删项目本身
                    s.query(NextWeekPlan).filter(
                        NextWeekPlan.project_id == payload["id"],
                        NextWeekPlan.week_start == pws_d, NextWeekPlan.week_end == pwe_d,
                    ).delete()
                    s.commit()
                elif action == "delete_task":
                    delete_task(s, payload["id"])
                elif action == "delete_plan": delete_plan(s, payload["id"])
                elif action == "edit_name":
                    if payload["type"] == "project": update_project(s, payload["id"], payload["value"])
                    elif payload["type"] == "task": update_task(s, payload["id"], description=payload["value"])
                    elif payload["type"] == "plan": update_plan(s, payload["id"], description=payload["value"])
                elif action == "edit_hours":
                    if payload["type"] == "task":
                        update_task(s, payload["id"], hours=validate_hours(float(payload["value"])))
                elif action == "add_subtask":
                    pt = payload["parent_type"]; pid = payload["parent_id"]
                    name = payload["name"]; vh = validate_hours(float(payload.get("hours", 0))) if payload.get("hours") else None
                    if pt == "project":
                        if active_tab == "current": create_task(s, pid, name, vh, ws_d, we_d)
                        else: create_plan(s, pid, name, pws_d, pwe_d)
                    elif pt == "task":
                        task = get_task(s, pid)
                        if task:
                            if active_tab == "current": create_task(s, task.project_id, name, vh, ws_d, we_d, parent_id=pid)
            except Exception as e:
                logger.exception(f"JS cmd failed: {action}")
            finally: s.close()
            return ""

        js_trigger.click(handle_js_command, inputs=[js_cmd, ws_state, we_state, pws_state, pwe_state, custom_h_state, tab_state], outputs=[js_cmd]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        # ── 全局新增任务 ──
        def handle_global_add(proj, name, hours, ws_d, we_d, pws_d, pwe_d, active_tab):
            if not proj: return "❌ 请选择项目"
            if not name or not name.strip(): return "❌ 描述不能为空"
            pid = _proj_id(proj)
            if not pid: return "❌ 项目不存在"
            try: vh = validate_hours(float(hours)) if hours is not None else None
            except ValueError as e: return f"❌ {e}"
            s = _s()
            try:
                if active_tab == "current": create_task(s, pid, name.strip(), vh, ws_d, we_d)
                else: create_plan(s, pid, name.strip(), pws_d, pwe_d)
                return "✅ 已添加"
            except ValueError as e: return f"❌ {e}"
            finally: s.close()
        add_btn.click(handle_global_add, inputs=[add_proj_dd, add_name_tb, add_hours_num, ws_state, we_state, pws_state, pwe_state, tab_state], outputs=[add_msg]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        # ── 生成周报 ──
        def handle_report(ws_d, we_d, active_tab):
            s = _s()
            try:
                if active_tab == "plan":
                    plans = get_plans_by_target_week(s, ws_d, we_d)
                    if not plans: return "", "❌ 下周计划暂无数据"
                    result = generate_weekly_plan(s, ws_d, we_d, plans)
                    return result, f"✅ 计划已生成（{len(plans)} 条）"
                else:
                    report = generate_weekly_report(s, ws_d, we_d)
                    return report.content, f"✅ 周报已生成（{len(json.loads(report.task_ids))} 个任务）"
            except ValueError as e: return "", f"❌ {e}"
            except Exception as e: logger.exception("生成失败"); return "", f"❌ 失败: {e}"
            finally: s.close()
        report_btn.click(handle_report, inputs=[ws_state, we_state, tab_state], outputs=[report_out, report_msg])

        # ── 历史查询 ──
        def handle_history(ws_s, we_s, proj, status, kw):
            ws = _parse(ws_s) if ws_s else None; we = _parse(we_s) if we_s else None
            pid = _proj_id(proj) if proj else None; sv = status if status != "全部" else None
            kwv = kw.strip() if kw and kw.strip() else None
            s = _s()
            try: tasks = get_all_tasks(s, ws, we, pid, sv, kwv)
            finally: s.close()
            if not tasks: return '<div style="color:#888;padding:20px">没有匹配的任务</div>'
            from collections import defaultdict
            weeks = defaultdict(lambda: defaultdict(list))
            for t in tasks: weeks[f"{t.week_start} ~ {t.week_end}"][t.project.name].append(t)
            total = sum(t.hours or 0 for t in tasks)
            parts = [f'<div style="margin-bottom:8px">共 {len(tasks)} 条，总工时 {total:.1f}h</div>']
            for wk in sorted(weeks.keys(), reverse=True):
                pgs = weeks[wk]; wh = sum(t.hours or 0 for pp in pgs.values() for t in pp)
                wk_parts = []
                for pname, ptasks in pgs.items():
                    ph = sum(t.hours or 0 for t in ptasks)
                    rows = [f'<tr><td width="24">{"✅" if t.status=="completed" else "⬜"}</td><td>{t.description[:80]}{"…" if len(t.description)>80 else ""}</td><td width="50" align="right">{t.hours if t.hours else "—"}h</td></tr>' for t in ptasks]
                    wk_parts.append(f'<div style="margin-bottom:6px;border:1px solid #e0e0e0;border-radius:4px;overflow:hidden"><div style="background:#f9f9f9;padding:4px 8px;font-size:12px;font-weight:bold">📁 {pname} ({ph:.1f}h)</div><table width="100%" style="font-size:12px">{"".join(rows)}</table></div>')
                parts.append(f'<div style="margin-bottom:12px"><div style="font-weight:bold;margin-bottom:4px">📅 {wk} ({wh:.1f}h)</div>{"".join(wk_parts)}</div>')
            return "".join(parts)
        h_search_btn.click(handle_history, inputs=[h_ws_tb, h_we_tb, h_proj_dd, h_status_dd, h_kw_tb], outputs=[hist_html])

        # ── 设置页面 ──
        def refresh_proj_ui():
            pc = _proj_choices()
            return (_html_projects(), gr.update(choices=pc, value=None), gr.update(choices=pc, value=None))
        def _html_projects():
            s = _s()
            try: projects = list_projects(s)
            finally: s.close()
            if not projects: return '<div style="color:#888;padding:10px">暂无项目</div>'
            rows = [f'<tr><td>{p.name}</td><td style="font-size:11px;color:#888">{p.created_at.strftime("%Y-%m-%d")}</td></tr>' for p in projects]
            return '<table width="100%" style="border-collapse:collapse"><tr style="background:#f5f5f5"><th style="text-align:left;padding:4px 8px">名称</th><th style="text-align:left;padding:4px 8px;font-size:11px">创建时间</th></tr>' + "".join(rows) + '</table>'

        def handle_create_project(name):
            if not name or not name.strip(): return ("❌ 名称不能为空", *refresh_proj_ui())
            s = _s()
            try: create_project(s, name.strip()); msg = f"✅ 项目「{name.strip()}」已创建"
            except ValueError as e: msg = f"❌ {e}"
            finally: s.close()
            return (msg, *refresh_proj_ui())
        create_proj_btn.click(handle_create_project, inputs=[new_proj_tb], outputs=[proj_msg, proj_table_html, rename_proj_dd, del_proj_dd]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_rename_project(old, new):
            if not old: return ("❌ 请选择项目", *refresh_proj_ui())
            if not new or not new.strip(): return ("❌ 新名称不能为空", *refresh_proj_ui())
            pid = _proj_id(old)
            if not pid: return ("❌ 项目不存在", *refresh_proj_ui())
            s = _s()
            try: update_project(s, pid, new.strip()); msg = f"✅ 已重命名为「{new.strip()}」"
            except ValueError as e: msg = f"❌ {e}"
            finally: s.close()
            return (msg, *refresh_proj_ui())
        rename_proj_btn.click(handle_rename_project, inputs=[rename_proj_dd, rename_proj_tb], outputs=[proj_msg, proj_table_html, rename_proj_dd, del_proj_dd]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_delete_project(name):
            if not name: return ("❌ 请选择项目", *refresh_proj_ui())
            pid = _proj_id(name)
            if not pid: return ("❌ 项目不存在", *refresh_proj_ui())
            s = _s()
            try: r = delete_project(s, pid); msg = f"✅ 已删除「{name}」（{r['tasks']} 任务, {r['plans']} 计划）"
            except ValueError as e: msg = f"❌ {e}"
            finally: s.close()
            return (msg, *refresh_proj_ui())
        del_proj_btn.click(handle_delete_project, inputs=[del_proj_dd], outputs=[proj_msg, proj_table_html, rename_proj_dd, del_proj_dd]).then(refresh_tree, inputs=FULL_IN, outputs=TREE_OUT)

        def handle_save_settings(hours):
            s = _s()
            try:
                r = s.query(Setting).filter(Setting.key == "total_hours_per_week").first()
                if r: r.value = str(hours); r.updated_at = datetime.now()
                else: s.add(Setting(key="total_hours_per_week", value=str(hours)))
                s.commit(); return f"✅ 已保存：默认 {hours}h/周"
            finally: s.close()
        save_set_btn.click(handle_save_settings, inputs=[default_h_num], outputs=[set_msg])

        app.load(lambda: refresh_proj_ui(), outputs=[proj_table_html, rename_proj_dd, del_proj_dd])
        app.load(lambda: refresh_tree(dws, dwe, dpws, dpwe, None, "current"), outputs=TREE_OUT)

    return app


def main():
    build_app().launch(server_name="127.0.0.1", server_port=7860, share=False)


if __name__ == "__main__":
    main()
