# -*- coding: utf-8 -*-
# ============================================================================
#  聚合消息工作台 · mail 平台 HTML 网页报告生成器
#
#  读取 data/messages/mail.md（platform-mail skill 的唯一消息记录），
#  生成可直接在浏览器 / 聚合消息平台网页内打开的单文件 HTML 报告：
#    - data/reports/mail_YYYYMMDD.html  （按日留档）
#    - data/reports/mail_latest.html    （固定文件名，供平台页面直接嵌入）
#
#  视觉规范与平台其他报告（如猎聘候选人报告）保持一致：
#  单文件、内联样式、不依赖任何外部 CDN/图片，离线可渲染。
#
#  用法：
#    python gen_mail_report.py                      # 用默认相对路径
#    python gen_mail_report.py --messages <mail.md> --outdir <目录>
# ============================================================================

import argparse
import hashlib
import html
import os
import re
from datetime import datetime

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# 状态配色（与平台报告统一：未回复=琥珀色，已回复=绿色）
PILL_STYLE = {
    "N": "color:#ca8a04;background:#fef9c3",   # 新邮件/待回复
    "Y": "color:#16a34a;background:#dcfce7",   # 已回复/待跟进
}
PILL_TEXT = {"N": "待回复", "Y": "已回复"}


def stable_uid(sender):
    """与 platforms/mail.py 的 uid 口径保持一致，用于候选人去重计数。"""
    email_m = _EMAIL_RE.search(sender)
    email = email_m.group(0) if email_m else ""
    head = ""
    if "<" in sender:
        head = sender.split("<", 1)[0].strip().strip("\"'")
    if email:
        if head and head != email.split("@", 1)[0]:
            return "mail_" + hashlib.md5((head + "|" + email).encode("utf-8")).hexdigest()[:12]
        return "mail_" + email
    return "mail_unknown_" + hashlib.md5(sender.encode("utf-8")).hexdigest()[:12]


def split_sender(sender):
    """「姓名 <邮箱>」拆成 (姓名, 邮箱)；裸邮箱返回 (本地名, 完整邮箱)。"""
    s = sender.strip()
    m = re.match(r"^(.*?)\s*<([^>]+)>\s*$", s)
    if m:
        return m.group(1).strip().strip("\"'"), m.group(2).strip()
    em = _EMAIL_RE.search(s)
    if em:
        e = em.group(0)
        return e.split("@", 1)[0], e
    return s, ""


def parse_messages(md_path):
    rows = []
    with open(md_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            sender, content, ts, replied = parts[0], parts[1], parts[2], parts[3]
            replied = "Y" if replied.upper() == "Y" else "N"
            rows.append({"sender": sender, "content": content, "ts": ts, "replied": replied})
    # 按时间倒序（无法解析的排最后），保持同日稳定
    def sort_key(r):
        try:
            return datetime.strptime(r["ts"], "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.min
    rows.sort(key=sort_key, reverse=True)
    return rows


def load_status(path):
    """读取收集状态记录 data/reports/collection_status.json；不存在或损坏返回空。"""
    if not os.path.exists(path):
        return {"runs": []}
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except (ValueError, OSError):
        pass
    return {"runs": []}


def append_status(path, run):
    """追加一次收集记录（最新在前，最多保留 30 条）并落盘。"""
    import json
    data = load_status(path)
    data["runs"].insert(0, run)
    data["runs"] = data["runs"][:30]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def render_status(status):
    """渲染「最近收集状态」区：每个通道一张最新状态卡 + 最近收集明细表。"""
    runs = status.get("runs", []) if status else []
    if not runs:
        return ""
    # 每个通道取最新一条
    latest_by_channel = {}
    for r in runs:
        ch = r.get("channel", "未知通道")
        if ch not in latest_by_channel:
            latest_by_channel[ch] = r
    cards = []
    for r in latest_by_channel.values():
        ok = r.get("ok", True)
        pill = ("color:#16a34a;background:#dcfce7") if ok else ("color:#dc2626;background:#fee2e2")
        stext = "正常" if ok else "异常"
        account = html.escape(r.get("account", "") or "")
        new_n = int(r.get("new", 0) or 0)
        cards.append(
            """<div class="stat-card" style="min-width:180px">
      <div style="font-size:14px;font-weight:600">%s <span style="display:inline-block;margin-left:6px;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;%s">%s</span></div>
      <div class="stat-label" style="margin-top:4px">最近收集：%s ｜ 本次新增 <b style="color:%s">%d</b> 条</div>
      <div class="stat-label">%s</div>
    </div>"""
            % (
                html.escape(r.get("channel", "未知通道")),
                pill, stext,
                html.escape(r.get("time", "")),
                "#16a34a" if new_n else "#6b7280", new_n,
                account,
            )
        )
    rows_html = []
    for r in runs[:10]:
        ok = r.get("ok", True)
        pill = ("color:#16a34a;background:#dcfce7") if ok else ("color:#dc2626;background:#fee2e2")
        stext = "正常" if ok else "异常"
        rows_html.append(
            """<tr>
          <td style="font-size:13px;white-space:nowrap">%s</td>
          <td style="font-size:13px">%s</td>
          <td style="font-size:12px;color:#6b7280">%s</td>
          <td style="text-align:center;font-size:13px;font-weight:600">%s</td>
          <td style="text-align:center;font-size:13px">%s</td>
          <td style="text-align:center;font-size:13px">%s</td>
          <td style="text-align:center"><span style="display:inline-block;padding:2px 10px;border-radius:10px;font-weight:600;font-size:12px;%s">%s</span></td>
          <td style="font-size:12px;color:#6b7280">%s</td>
        </tr>"""
            % (
                html.escape(r.get("time", "")),
                html.escape(r.get("channel", "")),
                html.escape(r.get("account", "") or ""),
                r.get("new", 0),
                r.get("replied", 0),
                r.get("skipped", 0),
                pill, stext,
                html.escape(r.get("note", "") or ""),
            )
        )
    return """
  <h2 style="font-size:16px;margin:24px 0 10px;">最近收集状态</h2>
  <div class="stats">%s</div>
  <table><thead><tr>
    <th style="width:150px">收集时间</th><th style="width:110px">通道</th><th>账号</th>
    <th style="width:70px">新增</th><th style="width:70px">已回复</th><th style="width:70px">跳过</th>
    <th style="width:80px">状态</th><th>备注</th>
  </tr></thead><tbody>%s</tbody></table>""" % ("".join(cards), "".join(rows_html))


def render(rows, generated_at, status=None):
    total = len(rows)
    persons = len({stable_uid(r["sender"]) for r in rows})
    replied_n = sum(1 for r in rows if r["replied"] == "Y")
    pending_n = total - replied_n

    trs = []
    for i, r in enumerate(rows, 1):
        name, email = split_sender(r["sender"])
        pill = PILL_STYLE[r["replied"]]
        ptext = PILL_TEXT[r["replied"]]
        email_html = (
            '<div style="font-size:11px;color:#9ca3af;margin-top:2px;word-break:break-all">%s</div>'
            % html.escape(email) if email else ""
        )
        trs.append(
            """
        <tr>
          <td style="text-align:center;font-weight:600;color:#6b7280">%d</td>
          <td style="font-weight:600;white-space:nowrap">%s%s</td>
          <td style="font-size:13px;color:#374151">%s</td>
          <td style="font-size:13px;white-space:nowrap;color:#374151">%s</td>
          <td style="text-align:center"><span style="display:inline-block;padding:2px 10px;border-radius:10px;font-weight:600;font-size:13px;%s">%s</span></td>
        </tr>"""
            % (
                i,
                html.escape(name),
                email_html,
                html.escape(r["content"]),
                html.escape(r["ts"]),
                pill,
                ptext,
            )
        )

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>邮箱候选人回复报告（%d条）</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f9fafb; color: #111827; }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .meta { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
  .stats { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat-card { background: #fff; border-radius: 10px; padding: 14px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); min-width: 120px; }
  .stat-num { font-size: 24px; font-weight: 700; }
  .stat-label { font-size: 12px; color: #6b7280; margin-top: 2px; }
  table { width:100%%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  th { background: #f3f4f6; padding: 10px 12px; text-align: left; font-size: 13px; color: #374151; border-bottom: 2px solid #e5e7eb; }
  td { padding: 12px; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }
  tr:hover { background: #f9fafb; }
  tr:last-child td { border-bottom: none; }
  .empty { background:#fff;border-radius:10px;padding:32px;text-align:center;color:#6b7280;font-size:14px;box-shadow:0 1px 3px rgba(0,0,0,0.08);}
</style>
</head>
<body>
<div class="container">
  <h1>邮箱候选人回复报告（%d条）</h1>
  <div class="meta">生成时间：%s ｜ 数据来源：data/messages/mail.md ｜ 按时间倒序</div>
  <div class="stats">
    <div class="stat-card"><div class="stat-num">%d</div><div class="stat-label">消息总数</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#2563eb">%d</div><div class="stat-label">候选人数(去重)</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#16a34a">%d</div><div class="stat-label">已回复</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#ca8a04">%d</div><div class="stat-label">待回复</div></div>
  </div>
  %s
  <h2 style="font-size:16px;margin:24px 0 10px;">候选人消息明细</h2>
  %s
</div>
</body>
</html>""" % (
        total,
        total,
        html.escape(generated_at),
        total,
        persons,
        replied_n,
        pending_n,
        render_status(status),
        ('<table><thead><tr>'
         '<th style="width:40px">#</th>'
         '<th style="width:200px">发件人</th>'
         '<th>内容</th>'
         '<th style="width:150px">时间</th>'
         '<th style="width:90px">状态</th>'
         '</tr></thead><tbody>' + "".join(trs) + '</tbody></table>')
        if rows else '<div class="empty">暂无候选人回复消息</div>',
    )


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.dirname(here)  # 接入包根目录（tools 的上一级）
    ap = argparse.ArgumentParser()
    ap.add_argument("--messages", default=os.path.join(base, "data", "messages", "mail.md"))
    ap.add_argument("--outdir", default=os.path.join(base, "data", "reports"))
    # 记录本次收集结果（每个通道收集后调用一次；不传则只按已有记录渲染）
    ap.add_argument("--log-channel", help="通道名，如 Gmail / 飞书")
    ap.add_argument("--log-account", default="", help="本次收集的邮箱账号")
    ap.add_argument("--new", type=int, help="本次新增消息条数")
    ap.add_argument("--replied", type=int, default=0, help="本次已回复条数")
    ap.add_argument("--skipped", type=int, default=0, help="本次跳过的通知类邮件数")
    ap.add_argument("--unread-total", type=int, default=0, help="收集时未读总数")
    ap.add_argument("--anomaly", action="store_true", help="本次收集是否异常（登录态/网络/浏览器空间等）")
    ap.add_argument("--note", default="", help="备注，如 全邮箱0封未读")
    args = ap.parse_args()

    status_path = os.path.join(args.outdir, "collection_status.json")
    status = load_status(status_path)
    now = datetime.now()
    if args.log_channel and args.new is not None:
        run = {
            "time": now.strftime("%Y-%m-%d %H:%M"),
            "channel": args.log_channel,
            "account": args.log_account,
            "new": args.new,
            "replied": args.replied,
            "skipped": args.skipped,
            "unread": args.unread_total,
            "ok": not args.anomaly,
            "note": args.note,
        }
        status = append_status(status_path, run)

    rows = parse_messages(args.messages)
    page = render(rows, now.strftime("%Y-%m-%d %H:%M"), status)

    os.makedirs(args.outdir, exist_ok=True)
    dated = os.path.join(args.outdir, "mail_%s.html" % now.strftime("%Y%m%d"))
    latest = os.path.join(args.outdir, "mail_latest.html")
    for path in (dated, latest):
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
    print("rows=%d runs=%d" % (len(rows), len(status.get("runs", []))))
    print("written:", dated)
    print("written:", latest)


if __name__ == "__main__":
    main()
