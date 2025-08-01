#!/usr/bin/env python3

import base64
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from common import Logger

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

def get_email_provider(provider_name: str, api_key: str) -> EmailProviderBase:
  """Factory method to create the appropriate provider"""
  if provider_name.lower() == "sendgrid":
    return SendGridProvider(api_key)
  elif provider_name.lower() == "brevo":
    return BrevoProvider(api_key)
  else:
    raise ValueError(f"Unsupported email provider: {provider_name}")
