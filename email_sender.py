"""
邮件发送模块
通过网易 SMTP 发送 HTML 格式邮件
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.header import Header
from email import encoders
from pathlib import Path

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_TO

logger = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, to_addr: str = None, md_file_path: str = None) -> bool:
    """
    发送 HTML 邮件，可选择附带 Markdown 附件

    Args:
        subject: 邮件标题
        html_body: HTML 邮件正文
        to_addr: 收件人地址，默认使用配置中的 SMTP_TO
        md_file_path: Markdown 文件路径，若提供则作为附件添加

    Returns:
        True 表示发送成功
    """
    if not to_addr:
        to_addr = SMTP_TO or SMTP_USER

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8")

    # 附加纯文本版本（作为降级）
    from bs4 import BeautifulSoup
    try:
        text_body = BeautifulSoup(html_body, "lxml").get_text(" ", strip=True)
    except Exception:
        text_body = "（请使用支持 HTML 的邮件客户端查看）"

    msg.attach(MIMEText(text_body[:2000], "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 附加 Markdown 附件
    if md_file_path:
        md_path = Path(md_file_path)
        if md_path.exists():
            with open(md_path, "rb") as f:
                attachment = MIMEBase("text", "markdown", filename=md_path.name)
                attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=("utf-8", "", md_path.name),
            )
            msg.attach(attachment)
            logger.info(f"  已附带附件: {md_path.name}")
        else:
            logger.warning(f"Markdown 附件不存在，跳过: {md_file_path}")

    logger.info(f"发送邮件 → {to_addr}（主题: {subject}）")

    try:
        # SSL 直连（端口 465）
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("邮件发送成功")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP 认证失败！请检查 SMTP_USER 和 SMTP_PASSWORD（网易邮箱需使用授权码，不是登录密码）"
        )
        raise
    except smtplib.SMTPException as e:
        logger.error(f"SMTP 发送失败: {e}")
        raise
    except Exception as e:
        logger.error(f"邮件发送异常: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    test_html = "<h1>测试邮件</h1><p>如果你看到这封邮件，说明 SMTP 配置正确。</p>"
    send_email("新闻投资参考 - 测试邮件", test_html)
