# AWS Deployment Guide — Sentri Analytics Pipeline

Deploy order: merge PRs #141 → #142 → #143 into main first, then follow this guide.

---

## Prerequisites (one-time setup)

### On your Mac

```bash
# AWS CLI — authenticated
brew install awscli
     # enter Access Key ID, Secret, region (e.g. us-east-1), output json

# SAM CLI
brew install aws-sam-cli

# Docker (SAM build uses it for Lambda packaging)
docker --version   # confirm installed
```

### In your AWS account

An IAM user or role with permissions to create Lambda, API Gateway, SQS, S3, RDS, VPC, and IAM roles. Attach `AdministratorAccess` to your deploy user for initial setup — tighten permissions after everything is verified working.

---

## Deploy the stack

```bash
cd aquilla-main/infra
sam build
sam deploy --guided
```

SAM will prompt for:

| Prompt | Value |
|---|---|
| Stack name | `sentri-analytics-prod` |
| AWS Region | `us-east-1` (or your preferred region) |
| DBMasterUsername | `sentri_admin` |
| DBMasterPassword | choose a strong password |
| Environment | `prod` |

Confirm the changeset when prompted. **Aurora takes ~10 minutes to provision** — everything else is fast. SAM saves your answers to `samconfig.toml` so future deploys just need `sam deploy`.

---

## After deploy — 3 manual steps

### 1. Run the schema SQL

Aurora is provisioned empty. Run `infra/db/schema.sql` once to create the three tables.

**Easiest method — RDS Query Editor (no bastion needed):**
1. AWS Console → RDS → your Aurora cluster → **Actions → Query**
2. Enable the Data API if prompted
3. Paste the contents of `infra/db/schema.sql` and run

**Alternative — psql via SSM port-forward:**
```bash
# Get Aurora endpoint from stack outputs
aws cloudformation describe-stacks \
  --stack-name sentri-analytics-prod \
  --query "Stacks[0].Outputs"

# Port-forward through SSM (no public endpoint needed)
# Then connect: psql -h 127.0.0.1 -U sentri_admin -d sentri -f infra/db/schema.sql
```

### 2. Create the Fleet API key

> ⚠️ **Not enforced as currently deployed.** The stack deploys an HTTP API
> (`AWS::Serverless::HttpApi`), which does not support API keys or usage plans —
> a key created here cannot be attached to the ingest endpoint and is ignored by
> the Lambda. The steps below describe the *intended* REST-API auth model. Until
> the gateway is migrated, the `/ingest` endpoint accepts unauthenticated
> requests and the "No API key → 403" check below will return `200`. See the
> 2026-06-16 addendum in `docs/adr/ADR-009-analytics-ingest-api-gateway-lambda.md`
> for the gap and the migration steps to make this real.

SAM deploys the API Gateway but does not auto-create an API key.

1. AWS Console → **API Gateway → API Keys → Create API Key**
   - Name: `sentri-fleet-key`
   - Auto-generate value
2. **Usage Plans → Create Usage Plan**
   - Attach your API + stage (`prod`)
   - Attach the `sentri-fleet-key` key
3. Copy the key value — this is your `AQ_SYNC_API_KEY`

### 3. Note the ingest endpoint

```bash
aws cloudformation describe-stacks \
  --stack-name sentri-analytics-prod \
  --query "Stacks[0].Outputs[?OutputKey=='IngestEndpoint'].OutputValue" \
  --output text
```

The value looks like:
```
https://<id>.execute-api.us-east-1.amazonaws.com/prod/ingest
```

This is your `AQ_SYNC_ENDPOINT`. Save both values — you'll push them to devices in the next step (#137).

---

## Smoke test

Run this before touching any device to confirm the full pipeline is working.

### Valid request — should return `200 {"queued": 1}`

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: <your-fleet-api-key>" \
  -d '{
    "device_id": "test-device-001",
    "events": [{
      "id": 1,
      "event_type": "run_complete",
      "created_at": "2026-06-10T12:00:00Z",
      "payload": {
        "profile": "basic_pcr.json",
        "run_name": "smoke-test",
        "aborted": false,
        "calls": [
          {"well": 1, "channel": "fam", "call": "Detected", "cq": 22.5}
        ]
      }
    }]
  }' \
  https://<id>.execute-api.us-east-1.amazonaws.com/prod/ingest
```

### No API key — should return `403` (intended; currently returns `200`)

> Until the gateway is migrated to a REST API with a usage plan (or in-Lambda
> key validation is added), this request returns `200`, not `403` — the
> `x-api-key` header is not checked. See the ADR-009 addendum.

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"device_id": "test", "events": []}' \
  https://<id>.execute-api.us-east-1.amazonaws.com/prod/ingest
```

### Verify the data landed

Wait ~30 seconds for SQS → Lambda 2 → S3 → Lambda 3 to process, then check:

```bash
# S3 archive
aws s3 ls s3://sentri-raw-events-<account-id>/2026-06-10/test-device-001/

# Aurora rows (via RDS Query Editor or psql)
SELECT * FROM devices;
SELECT * FROM runs;
SELECT * FROM run_results;
```

Expected: 1 row in `devices`, 1 row in `runs`, 1 row in `run_results`.

---

## Troubleshooting

### Check Lambda logs

```bash
aws logs tail /aws/lambda/sentri-ingest-handler --follow
aws logs tail /aws/lambda/sentri-s3-archiver --follow
aws logs tail /aws/lambda/sentri-aurora-loader --follow
```

### Check the dead-letter queue

Messages here mean Lambda 2 or Lambda 3 failed 3 times. Check the corresponding log group for the error.

```bash
aws sqs get-queue-attributes \
  --queue-url $(aws sqs get-queue-url --queue-name sentri-event-dlq --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages
```

### Lambda 3 can't connect to Aurora (most common issue)

Aurora is in a private subnet and Lambda 3 connects via VPC. If logs show connection timeouts:

1. AWS Console → EC2 → Security Groups → find `sentri-aurora-loader-LambdaSecurityGroup`
2. Confirm it has an outbound rule: **TCP port 5432 → DBSecurityGroup**
3. Confirm `DBSecurityGroup` has an inbound rule: **TCP port 5432 ← LambdaSecurityGroup**

SAM sets this up automatically but the console is the fastest way to verify.

### Replay events from S3

If Aurora was down and Lambda 3 didn't process some files, replay them by re-triggering the S3 notification:

```bash
# Re-put the object to trigger a new ObjectCreated event
aws s3 cp \
  s3://sentri-raw-events-<account-id>/2026-06-10/dev1/42.json \
  s3://sentri-raw-events-<account-id>/2026-06-10/dev1/42.json \
  --metadata-directive REPLACE
```

---

## Next steps after successful smoke test

1. Push `AQ_SYNC_ENDPOINT` and `AQ_SYNC_API_KEY` to devices — see issue #137
2. Run the end-to-end integration test on a real Sentri — see issue #138
3. Run the inconclusive rate query against real data:

```sql
SELECT
    r.protocol,
    COUNT(*) FILTER (WHERE rr.call = 'Inconclusive')                     AS inconclusive_count,
    COUNT(*) FILTER (WHERE rr.call != 'ROX Unavailable')                AS eligible_count,
    ROUND(
        COUNT(*) FILTER (WHERE rr.call = 'Inconclusive')::numeric /
        NULLIF(COUNT(*) FILTER (WHERE rr.call != 'ROX Unavailable'), 0),
    4) AS inconclusive_rate
FROM run_results rr
JOIN runs r USING (run_id)
WHERE r.aborted = false
GROUP BY r.protocol
ORDER BY inconclusive_rate DESC;
```

---

## Reference

- Architecture decision: `docs/adr/ADR-009-analytics-ingest-api-gateway-lambda.md`
- Pipeline PRD: `specs/data-pipline/analytics-pipeline-prd.md`
- SAM template: `infra/template.yaml`
- Schema: `infra/db/schema.sql`
