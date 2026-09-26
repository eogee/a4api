"""反馈邮件发送：提交后直达开发者邮箱（eogee@qq.com）。

配置来自 mail_secrets.py（私有文件，被 .gitignore 排除、随安装包分发）；
未配置或发送失败不影响反馈入库——反馈始终先落本地库，邮件尽力送达。
截图以附件形式随信发送（EoListen 的做法是入库后台看图，本应用无后台，
邮件附件是截图送达开发者的唯一通道）。
"""
import logging
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from . import mail_secrets  # 私有凭据文件（.gitignore 排除），克隆后不存在属正常
except ImportError:  # 缺失时反馈仅入库、不发邮件
    mail_secrets = None

log = logging.getLogger(__name__)

_KIND_LABEL = {"bug": "Bug 报告", "feature": "功能需求"}


def _build_message(fb_id: int, kind: str, content: str, contact: str,
                   env_lines: list[str], log_excerpt: str,
                   images: list[tuple[str, str, bytes]]) -> MIMEMultipart:
    kind_label = _KIND_LABEL.get(kind, kind)
    lines = [
        f"a4agent 收到新的{'问题反馈' if kind == 'bug' else '功能需求'}（#{fb_id}）",
        "",
        f"反馈类型：{kind_label}",
        f"提交时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"联系方式：{contact or '（未填写）'}",
        "",
        "## 问题描述",
        "",
        content,
    ]
    if env_lines:
        lines += ["", "## 环境信息", "", *env_lines]
    if log_excerpt:
        lines += ["", "## 日志片段", "", log_excerpt]
    if images:
        lines += ["", f"（{len(images)} 张截图见附件）"]

    msg = MIMEMultipart("mixed")
    msg["From"] = f"a4agent<{mail_secrets.SMTP_SENDER or mail_secrets.SMTP_USER}>"
    msg["To"] = mail_secrets.FEEDBACK_NOTIFY_EMAIL
    msg["Subject"] = f"[a4agent {kind_label}] #{fb_id}"
    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))

    for seq, (name, mime, data) in enumerate(images, start=1):
        subtype = (mime.partition("/")[2] or "png").split(";")[0]
        img = MIMEImage(data, _subtype=subtype)
        img.add_header("Content-Disposition", "attachment",
                       filename=f"fb{fb_id}-{seq}-{name}")
        msg.attach(img)
    return msg


def send_feedback_mail(fb_id: int, kind: str, content: str, contact: str,
                       env_lines: list[str], log_excerpt: str,
                       images: list[tuple[str, str, bytes]]) -> bool:
    """发送反馈邮件；未配置凭据或发送失败返回 False（调用方回写 emailed 标志）。"""
    if mail_secrets is None:
        log.info("反馈 #%s 未发邮件：缺少 mail_secrets.py（SMTP 凭据未配置）", fb_id)
        return False
    if not getattr(mail_secrets, "SMTP_USER", "") or not getattr(mail_secrets, "SMTP_PASS", ""):
        log.info("反馈 #%s 未发邮件：SMTP 未配置", fb_id)
        return False
    try:
        msg = _build_message(fb_id, kind, content, contact, env_lines, log_excerpt, images)
        server = smtplib.SMTP(mail_secrets.SMTP_HOST, mail_secrets.SMTP_PORT, timeout=15)
        try:
            server.starttls()
            server.login(mail_secrets.SMTP_USER, mail_secrets.SMTP_PASS)
            server.send_message(msg)
        finally:
            server.quit()
        return True
    except Exception as e:  # noqa: BLE001 邮件失败不影响反馈入库
        log.warning("反馈 #%s 邮件发送失败：%s", fb_id, e)
        return False
