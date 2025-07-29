#!/usr/bin/env python3
"""
Email Util Module
Multi-provider email handling with support for SendGrid and Brevo

This module provides a flexible email client that supports multiple email service providers
through a pluggable architecture. Configuration can be loaded from dictionaries, config files,
or created programmatically.

Usage Examples:
  # Create config from dictionary
  config_dict = {
    "provider": "sendgrid",
    "api_key": "your-api-key",
    "sender": "sender@example.com",
    "recipients": "recipient@example.com"
  }
  config = load_email_config(config_dict)
  handler = EmailHelper(config)
  
  # Create config programmatically
  config = create_email_config(
    provider="brevo",
    api_key="your-api-key", 
    sender="sender@example.com",
    recipients="recipient@example.com"
  )
  handler = EmailHelper(config)
  
  # Send email
  success = handler.send_email(
    subject="Test Email",
    html_content="<h1>Hello World</h1>",
    attachment_data=b"file content",
    attachment_filename="report.txt"
  )
"""

import os
import base64
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from common import Logger

logger = Logger.getLogger()

class EmailProvider(Enum):
  """Supported email service providers"""
  SENDGRID = "sendgrid"
  BREVO = "brevo"

@dataclass
class EmailConfig:
  provider: EmailProvider = EmailProvider.SENDGRID
  api_key: str = None
  sender: str = None
  recipients: str = None
  subject_formatter: str = None
  body_template: str = None  # File path to email template
  include_attachment: bool = True

class EmailProviderBase(ABC):
  """Abstract base class for email service providers"""
  
  def __init__(self, config: EmailConfig):
    self.config = config
    self._validate_config()
  
  @abstractmethod
  def _validate_config(self):
    """Validate provider-specific configuration"""
    pass
  
  @abstractmethod
  def send_email(self, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    """Send email with optional attachment"""
    pass

class SendGridProvider(EmailProviderBase):
  """SendGrid email service provider"""
  
  def __init__(self, config: EmailConfig):
    super().__init__(config)
  
  def _validate_config(self):
    """Validate SendGrid configuration"""
    if not self.config.api_key:
      raise ValueError("SendGrid API key is required")
    if not self.config.sender:
      raise ValueError("Email sender is required")
    if not self.config.recipients:
      raise ValueError("Email recipients are required")
  
  def send_email(self, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    """Send email using SendGrid"""
    try:
      from sendgrid import SendGridAPIClient
      from sendgrid.helpers.mail import Mail, MimeType, Attachment
      
      # Construct email
      email = Mail()
      email.from_email = self.config.sender
      
      # Add recipients
      recipients = self.config.recipients.split(';')
      for recipient in recipients:
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
      sendgrid = SendGridAPIClient(self.config.api_key)
      response = sendgrid.send(email)
      
      if response.status_code > 400:
        logger.error(f"SendGrid API failed: error={response.status_code}")
        return False
      else:
        logger.info(f"SendGrid: Email sent successfully to {len(recipients)} recipients.")
        return True
    except ImportError:
      logger.error("SendGrid library not installed. Install with: pip install sendgrid")
      return False
    except Exception as e:
      logger.error(f"SendGrid: Failed to send email: {e}")
      return False

class BrevoProvider(EmailProviderBase):
  """Brevo (formerly Sendinblue) email service provider"""
  
  def __init__(self, config: EmailConfig):
    super().__init__(config)
  
  def _validate_config(self):
    """Validate Brevo configuration"""
    if not self.config.api_key:
      raise ValueError("Brevo API key is required")
    if not self.config.sender:
      raise ValueError("Email sender is required")
    if not self.config.recipients:
      raise ValueError("Email recipients are required")
  
  def send_email(self, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    """Send email using Brevo"""
    try:
      import requests
      
      # Brevo API endpoint
      url = "https://api.brevo.com/v3/smtp/email"
      
      # Headers
      headers = {
        "accept": "application/json",
        "api-key": self.config.api_key,
        "content-type": "application/json"
      }
      
      # Prepare recipients
      recipients = []
      for recipient in self.config.recipients.split(';'):
        recipients.append({"email": recipient.strip()})
      
      # Prepare email data
      email_data = {
        "sender": {"email": self.config.sender},
        "to": recipients,
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
        logger.info(f"Brevo: Email sent successfully to {len(recipients)} recipients. Message ID: {message_id}")
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

class EmailHelper:
  """Generic email helper that delegates to specific providers"""
  
  def __init__(self, email_config: EmailConfig):
    """Initialize email handler with configuration"""
    self.config = email_config
    self.provider = self._create_provider()
  
  def _create_provider(self) -> EmailProviderBase:
    """Factory method to create the appropriate provider"""
    if self.config.provider == EmailProvider.SENDGRID:
      return SendGridProvider(self.config)
    elif self.config.provider == EmailProvider.BREVO:
      return BrevoProvider(self.config)
    else:
      raise ValueError(f"Unsupported email provider: {self.config.provider}")
  
  def send_email(self, subject: str, html_content: str, attachment_data: Optional[bytes] = None, 
                 attachment_filename: Optional[str] = None, attachment_type: Optional[str] = None) -> bool:
    """Send email with optional attachment using the configured provider
    
    Args:
      subject: Email subject line
      html_content: HTML body content
      attachment_data: Binary data for attachment (optional)
      attachment_filename: Name for the attachment file (optional)
      attachment_type: MIME type for attachment (optional)
    
    Returns:
      bool: True if email sent successfully, False otherwise
    """
    return self.provider.send_email(subject, html_content, attachment_data, attachment_filename, attachment_type)

def create_email_config(provider: str, api_key: str, sender: str, recipients: str, 
                       subject: str = "", body_template: str = "", include_attachment: bool = True) -> EmailConfig:
  """Create EmailConfig object with simplified parameters
  
  Args:
    provider: Email provider name ('sendgrid' or 'brevo')
    api_key: API key for the provider
    sender: Sender email address
    recipients: Recipient email addresses (semicolon separated)
    subject: Subject formatter string (optional)
    body_template: Path to email template file (optional)
    include_attachment: Boolean to include attachments (optional, default True)
  
  Returns:
    EmailConfig: Configured email settings
  """
  config_dict = {
    "provider": provider,
    "api_key": api_key,
    "sender": sender,
    "recipients": recipients,
    "subject": subject,
    "body_template": body_template,
    "attachment": include_attachment
  }  
  return load_email_config(config_dict)

def load_email_config(config_dict: dict) -> EmailConfig:
  """Load email configuration from dictionary
  
  Args:
    config_dict: Dictionary containing email configuration with keys:
      - provider: Email provider name ('sendgrid' or 'brevo')
      - api_key: API key for the provider (optional, can use environment variable)
      - sender: Sender email address
      - recipients: Recipient email addresses (semicolon separated)
      - subject: Subject formatter string (optional)
      - body_template: Path to email template file (optional)
      - attachment: Boolean to include attachments (optional, default True)
  
  Returns:
    EmailConfig: Configured email settings
    
  Raises:
    ValueError: If required configuration is missing or invalid
  """
  try:
    settings = EmailConfig()
    
    # Get email provider (default to SendGrid for backward compatibility)
    provider_name = config_dict.get("provider", "brevo").lower().strip()
    try:
      settings.provider = EmailProvider(provider_name)
    except ValueError:
      logger.warning(f"Unknown email provider '{provider_name}', defaulting to SendGrid")
      settings.provider = EmailProvider.SENDGRID
    
    # Get API key - first try from dict, then from environment variable
    api_key = config_dict.get("api_key")
    if not api_key:
      # Use generic API key name
      api_key_env = 'EMAIL_API_KEY'  # Fallback
      if api_key_env not in os.environ:
        raise ValueError(f"API key not provided in config and {api_key_env} environment variable not set")
      api_key = os.environ[api_key_env]    
    settings.api_key = api_key.strip() if api_key else None
    
    # Load required email settings
    settings.sender = config_dict.get("sender", "").strip()
    if not settings.sender:
      raise ValueError("Sender email address is required")
    
    raw_recipients = config_dict.get("recipients", "").strip()
    if not raw_recipients:
      raise ValueError("Recipients are required")
    
    # Clean up recipients (remove whitespace)
    white_spaces = ' \n'
    settings.recipients = raw_recipients.translate({ord(i): None for i in white_spaces})
    
    # Optional settings
    settings.subject_formatter = config_dict.get("subject", "").strip()
    settings.body_template = config_dict.get("body_template", "").strip()
    settings.include_attachment = config_dict.get("attachment", True)
    
    # Convert string boolean values
    if isinstance(settings.include_attachment, str):
      settings.include_attachment = settings.include_attachment.lower() in ('true', '1', 'yes', 'on')
    
    logger.debug(f"Email configuration loaded for provider: {settings.provider.value}")
    return settings    
  except Exception as e:
    logger.error(f"Email configuration is invalid: {e}")
    raise
