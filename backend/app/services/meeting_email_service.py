import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config.settings import Settings, get_settings
from app.core.errors import AppError


class MeetingEmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.templates = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def send_meeting_email(self, *, meeting: dict[str, object], attendee_email: str) -> dict[str, object]:
        if not self.settings.has_mail_config:
            raise AppError(
                status_code=400,
                code="mail_not_configured",
                message="Mail configuration is incomplete.",
            )
        if not attendee_email:
            raise AppError(
                status_code=409,
                code="lead_email_missing",
                message="Lead email is required before a meeting email can be sent.",
            )

        organizer = self._organizer()
        html_body = self.templates.get_template("email_template.html").render(
            meeting=meeting,
            organizer=organizer,
        )
        text_body = self._build_text_body(meeting)

        message = MIMEMultipart("alternative")
        message["Subject"] = f"Meeting Invite: {meeting.get('title') or 'SPARX Meeting'}"
        message["From"] = self.settings.mail_default_sender or self.settings.mail_username
        message["To"] = attendee_email
        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        smtp_cls = smtplib.SMTP_SSL if self.settings.mail_use_ssl else smtplib.SMTP
        with smtp_cls(self.settings.mail_server, self.settings.mail_port) as server:
            if self.settings.mail_use_tls and not self.settings.mail_use_ssl:
                server.starttls()
            server.login(self.settings.mail_username, self.settings.mail_password_text)
            server.sendmail(self.settings.mail_username, [attendee_email], message.as_string())

        return {
            "status": "sent",
            "recipient": attendee_email,
            "template": "email_template.html",
        }

    def _organizer(self) -> dict[str, str]:
        sender = self.settings.mail_default_sender or self.settings.mail_username or "SPARX"
        if "<" in sender and ">" in sender:
            name = sender.split("<", 1)[0].strip().strip('"') or "SPARX"
            email = sender.split("<", 1)[1].split(">", 1)[0].strip()
            return {"name": name, "email": email}
        return {"name": "SPARX", "email": sender}

    @staticmethod
    def _build_text_body(meeting: dict[str, object]) -> str:
        lines = [
            f"Meeting: {meeting.get('title') or 'SPARX Meeting'}",
            f"When: {meeting.get('start_datetime') or '-'}",
            f"Ends: {meeting.get('end_datetime') or '-'}",
            f"Duration: {meeting.get('duration_minutes') or '-'} minutes",
            f"Google Meet: {meeting.get('meet_link') or '-'}",
            f"Calendar: {meeting.get('event_link') or '-'}",
        ]
        return "\n".join(lines)


@lru_cache
def get_meeting_email_service() -> MeetingEmailService:
    return MeetingEmailService(get_settings())
