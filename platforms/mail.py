# -*- coding: utf-8 -*-
# ============================================================================
#  聚合消息工作台 · mail 平台接入（邮箱回复消息）
#  基于 _template.py（SPEC 1.0）实现，接入方式 B（实现 Adapter 类）
#
#  数据链路：
#    platform-mail skill 每天通过 lark-cli（飞书企业邮箱，用户身份由平台注入）
#    拉取收件箱未读回复
#      → 追加写入 data/messages/mail.md（发件人 | 内容 | 时间 | 已回复(Y/N)）
#      → 本 Adapter 读取该文件，解析为候选人卡片返回给桥服务
#    注意：招聘平台通知邮件（如 BOSS 直聘）发件人是统一服务邮箱、候选人姓名
#    在「姓名 <服务邮箱>」的姓名位，uid 必须把姓名计入，避免不同候选人被合并。
#
#  首次接入步骤：
#    1. 本文件放到平台工程 platforms/ 目录，文件名保持 mail.py
#    2. 确认 data/messages/mail.md 存在（可由 platform-mail skill 自动创建）
#    3. 桥服务热重载后，设置页应显示「邮箱 已接入」
#
#  字段口径：见 _template.py 顶部「候选人字段规范」，未知一律留空，禁止编造。
# ============================================================================

import os
import re
import hashlib

# ----------------------------------------------------------------------------
#  平台元信息
# ----------------------------------------------------------------------------
PLATFORM = {
    "key": "mail",        # 必填，六选一：liepin/maimai/boss/linkedin/xhs/mail
    "name": "邮箱",        # 显示名，页面平台卡上显示
    "version": "0.1",     # 版本号，会显示在页面设置页
}

# ----------------------------------------------------------------------------
#  路径与口径
# ----------------------------------------------------------------------------
# 平台工程根目录（platforms/ 的上一级）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 消息记录文件：platform-mail skill 的唯一输出，禁止手工改动
_MESSAGES_FILE = os.path.join(_BASE_DIR, "data", "messages", "mail.md")

# 邮件回复视为候选人的基础匹配分（0-100）。
# 口径说明：邮件回复属于「已触达且有意向」线索，页面门槛默认 70，
# 基础分给 75 保证能进列表；全队打分口径需统一，可按需调整此常量，
# 后续也可升级为按 JD 关键词做 AI 比对打分。
MATCHED_BASE = 75

# 正文可提取的中国大陆手机号（提取不到留空，不编造）
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
# 邮箱地址
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 消息正文截断长度（配合 bullets 展示）
_CONTENT_MAX = 60


def _extract_email(text):
    m = _EMAIL_RE.search(text)
    return m.group(0) if m else ""


def _extract_phone(text):
    m = _PHONE_RE.search(text)
    return m.group(0) if m else ""


def _sender_name(sender):
    """从发件人字段提取姓名：优先 <> 前的显示名，其次邮箱本地部分。"""
    s = sender.strip()
    if "<" in s and ">" in s:
        head = s.split("<", 1)[0].strip().strip("\"'")
        if head:
            return head
    email = _extract_email(s)
    if email:
        return email.split("@", 1)[0]
    return s or "未知发件人"


def _stable_uid(sender):
    """uid 必须稳定且一人一卡：
    - 普通个人邮件（只有邮箱）：mail_<邮箱>
    - 「姓名 <邮箱>」（含平台通知邮件，同一服务邮箱对应不同候选人）：
      用 姓名|邮箱 的散列，保证不同候选人不合并、同一候选人多次同步仍去重
    - 完全没有邮箱：发件人字符串散列
    """
    email = _extract_email(sender)
    head = ""
    if "<" in sender:
        head = sender.split("<", 1)[0].strip().strip("\"'")
    if email:
        if head and head != email.split("@", 1)[0]:
            digest = hashlib.md5((head + "|" + email).encode("utf-8")).hexdigest()[:12]
            return "mail_" + digest
        return "mail_" + email
    digest = hashlib.md5(sender.encode("utf-8")).hexdigest()[:12]
    return "mail_unknown_" + digest


def _truncate(text, limit=_CONTENT_MAX):
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "……"


class Adapter(object):
    """
    mail 平台接入。未实现的方法（read/contacted/send/resume）由桥服务
    回落处理，本平台暂不强制。
    """

    # ---------- 健康检测 ----------
    def health(self):
        if not os.path.exists(_MESSAGES_FILE):
            return {
                "status": "offline",
                "error": "data/messages/mail.md 不存在，请先运行 platform-mail skill 收集一次邮箱回复",
                "login_required": False,
            }
        return {"status": "online", "latency": 10}

    # ---------- 拉取消息 ----------
    def messages(self):
        records = self._parse_records()
        # 同一发件人合并为一张卡片：按文件顺序保留最新一条；
        # 只要该发件人任一条消息已回复，状态即「待跟进」，否则「新邮件」。
        by_uid = {}
        for sender, content, ts, replied in records:
            uid = _stable_uid(sender)
            if uid not in by_uid:
                by_uid[uid] = {
                    "uid": uid,
                    "name": _sender_name(sender),
                    "email": _extract_email(sender),
                    "phone": "",
                    "status": "新邮件",
                    "replied": False,
                    "content": content,
                    "ts": ts,
                }
            cur = by_uid[uid]
            # 以最新一条为准（消息文件按时间追加）
            cur["content"] = content
            cur["ts"] = ts
            # 手机号跨全部消息提取，取最先出现的非空值
            if not cur["phone"]:
                cur["phone"] = _extract_phone(content)
            if replied == "Y":
                cur["replied"] = True
                cur["status"] = "待跟进"

        candidates = []
        for cur in by_uid.values():
            candidates.append({
                "uid": cur["uid"],
                "name": cur["name"],
                "role": "",                    # 未知不编造
                "org": "",                     # 未知不编造
                "city": "",
                "edu": "",
                "years": "",
                "phone": cur["phone"],
                "email": cur["email"],
                "matched": MATCHED_BASE,       # 口径见文件头说明
                "level": "",
                "status": cur["status"],
                "bullets": [
                    "邮件回复（%s）：%s" % (cur["ts"], _truncate(cur["content"])),
                ],
                "exp": [],
                "weakness": "",                # 未知不编造
                "note": "来自邮箱回复 %s · 已回复=%s" % (
                    cur["ts"], "Y" if cur["replied"] else "N"
                ),
                "resumeUrl": "",
            })
        return {"candidates": candidates}

    # ---------- 重连（页面刷新按钮调用）----------
    def reconnect(self, payload=None):
        """邮箱登录态无法由桥服务自动恢复：首次登录/重连均需先向用户确认，
        由用户本人在浏览器完成登录。"""
        return {
            "status": "offline",
            "login_required": True,
            "error": "需要在浏览器重新登录邮箱（首次登录需先向用户确认，由用户本人完成）",
        }

    # ------------------------------------------------------------------
    #  内部：解析 data/messages/mail.md
    #  每行：发件人 | 内容 | 时间 | 已回复(Y/N)
    # ------------------------------------------------------------------
    def _parse_records(self):
        records = []
        if not os.path.exists(_MESSAGES_FILE):
            return records
        with open(_MESSAGES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                sender, content, ts, replied = parts[0], parts[1], parts[2], parts[3]
                replied = "Y" if replied.upper() == "Y" else "N"
                records.append((sender, content, ts, replied))
        return records
