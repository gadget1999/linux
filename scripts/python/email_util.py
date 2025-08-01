#!/usr/bin/env python3

import base64
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from common import Logger, CLIParser
import sys
import os

logger = Logger.getLogger()

class EmailProviderBase(ABC):
  """Abstract base class for email service providers"""
  
  def __init__(self, api_key: str):
    self._api_key = api_key
    if not self._api_key:
      raise ValueError("Email API key is required")
  
  @abstractmethod
  def send_email(self, sender: str, recipients: str, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    """Send email with optional attachment"""
    pass

class SendGridProvider(EmailProviderBase):
  def __init__(self, api_key: str):
    super().__init__(api_key)
  
  def send_email(self, sender: str, recipients: str, subject: str,
                 html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    try:
      from sendgrid import SendGridAPIClient
      from sendgrid.helpers.mail import Mail, MimeType, Attachment
      
      # Construct email
      email = Mail()
      email.from_email = sender
      
      # Add recipients
      for recipient in recipients.split(';'):
        email.add_to(recipient.strip())
      
      # Set subject and content
      email.subject = subject
      email.add_content(html_content, MimeType.html)
      
      # Add attachment if provided
      if attachment_data and attachment_filename:
        attachment = Attachment()
        attachment.file_content = base64.b64encode(attachment_data).decode()
        attachment.file_type = attachment_type or "application/octet-stream"
        attachment.file_name = attachment_filename
        attachment.disposition = "attachment"
        email.add_attachment(attachment)
      
      # Send email via SendGrid
      sendgrid = SendGridAPIClient(self._api_key)
      response = sendgrid.send(email)
      
      if response.status_code > 400:
        logger.error(f"SendGrid API failed: error={response.status_code}")
        return False
      else:
        logger.info(f"SendGrid: Email sent successfully to {len(recipients.split(';'))} recipients.")
        return True
    except ImportError:
      logger.error("SendGrid library not installed. Install with: pip install sendgrid")
      return False
    except Exception as e:
      logger.error(f"SendGrid: Failed to send email: {e}")
      return False

class BrevoProvider(EmailProviderBase):
  def __init__(self, api_key: str):
    super().__init__(api_key)
  
  def send_email(self, sender: str, recipients: str, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    try:
      import requests
      
      # Brevo API endpoint
      url = "https://api.brevo.com/v3/smtp/email"
      
      # Headers
      headers = {
        "accept": "application/json",
        "api-key": self._api_key,
        "content-type": "application/json"
      }
      
      # Prepare recipients
      recips = []
      for recipient in recipients.split(';'):
        recips.append({"email": recipient.strip()})
      
      # Prepare email data
      email_data = {
        "sender": {"email": sender},
        "to": recips,
        "subject": subject,
        "htmlContent": html_content
      }
      
      # Add attachment if provided
      if attachment_data and attachment_filename:
        attachment_content = base64.b64encode(attachment_data).decode()
        email_data["attachment"] = [{
          "content": attachment_content,
          "name": attachment_filename,
          "type": attachment_type or "application/octet-stream"
        }]
      
      # Send email via API
      response = requests.post(url, headers=headers, json=email_data)
      if response.status_code == 201:
        response_data = response.json()
        message_id = response_data.get('messageId', 'unknown')
        logger.info(f"Brevo: Email sent successfully to {len(recips)} recipients. Message ID: {message_id}")
        return True
      else:
        logger.error(f"Brevo API error: {response.status_code} - {response.text}")
        return False
    except ImportError as e1:
      logger.error(f"Required library not available. Make sure 'requests' is installed: pip install requests. {e1}")
      return False
    except Exception as e2:
      logger.error(f"Brevo: Failed to send email: {e2}")
      return False

class GmailProvider(EmailProviderBase):
  def __init__(self, api_key: str):
    super().__init__(api_key)

  def send_email(self, sender: str, recipients: str, subject: str, html_content: str, attachment_data: Optional[bytes] = None,
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    try:
      import smtplib
      from email.mime.multipart import MIMEMultipart
      from email.mime.text import MIMEText
      from email.mime.base import MIMEBase
      from email import encoders
      
      # Gmail SMTP settings
      smtp_server = "smtp.gmail.com"
      smtp_port = 587
      username = sender
      password = self._api_key  # API key is the app password
      
      # Create message
      msg = MIMEMultipart()
      msg['From'] = sender
      msg['To'] = recipients
      msg['Subject'] = subject
      msg.attach(MIMEText(html_content, 'html'))
      
      # Add attachment if provided
      if attachment_data and attachment_filename:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{attachment_filename}"')
        msg.attach(part)
      
      # Connect and send
      server = smtplib.SMTP(smtp_server, smtp_port)
      server.starttls()
      server.login(username, password)
      server.sendmail(sender, recipients.split(';'), msg.as_string())
      server.quit()
      logger.info(f"Gmail: Email sent successfully to {len(recipients.split(';'))} recipients.")
      return True
    except ImportError as e1:
      logger.error(f"Required library not available for Gmail SMTP: {e1}")
      return False
    except Exception as e2:
      logger.error(f"Gmail: Failed to send email: {e2}")
      return False

def get_email_provider(provider_name: str, api_key: str) -> EmailProviderBase:
  """Factory method to create the appropriate provider"""
  if provider_name.lower() == "sendgrid":
    return SendGridProvider(api_key)
  elif provider_name.lower() == "brevo":
    return BrevoProvider(api_key)
  elif provider_name.lower() == "gmail":
    return GmailProvider(api_key)
  else:
    raise ValueError(f"Unsupported email provider: {provider_name}")

def send_email_cli(args):
  provider = args.provider
  api_key = os.environ["EMAIL_API_KEY"]
  sender = args.sender
  recipients = args.to
  subject = args.subject
  body = args.body
  attachment = args.attachment if hasattr(args, 'attachment') else None
  attachment_type = args.attachment_type if hasattr(args, 'attachment_type') else None

  attachment_data = None
  attachment_filename = None
  if attachment:
    if not os.path.isfile(attachment):
      logger.error(f"Attachment file not found: {attachment}")
      sys.exit(2)
    with open(attachment, 'rb') as f:
      attachment_data = f.read()
    attachment_filename = os.path.basename(attachment)

  provider_obj = get_email_provider(provider, api_key)
  provider_obj.send_email(
    sender=sender,
    recipients=recipients,
    subject=subject,
    html_content=body,
    attachment_data=attachment_data,
    attachment_filename=attachment_filename,
    attachment_type=attachment_type
  )

if __name__ == "__main__":
  CLI_config = {
    'arguments': [
      { 'name': '--provider', 'help': 'Email provider (sendgrid, brevo, gmail)', 'required': True },
      { 'name': '--sender', 'help': 'Sender email address', 'required': True },
      { 'name': '--to', 'help': 'Recipient email(s), separated by semicolon', 'required': True },
      { 'name': '--subject', 'help': 'Email subject', 'required': True },
      { 'name': '--body', 'help': 'Email body (HTML allowed)', },
      { 'name': '--attachment', 'help': 'Path to attachment file (optional)', 'action': 'store', },
      { 'name': '--attachment-type', 'help': 'Attachment MIME type (optional)', 'action': 'store', },
    ],
    'func': send_email_cli
  }
  CLIParser.run(CLI_config)
