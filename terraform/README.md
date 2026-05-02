# Terraform Alerting Notes

## SNS Email Confirmation

CloudWatch alarms publish to the `truerag-alerts` SNS topic.

The email subscription uses protocol `email` and **must be manually confirmed** by clicking the link sent by AWS SNS to `alert_email` after `terraform apply`.

Until confirmation, alarm notifications will not be delivered.
