# aquilla-main changes required to support sentri-analytics hosting modernization

Purpose: sentri-analytics is moving from a single hand-built EC2 box (`setup.sh`) to a baked-AMI Auto Scaling Group (see `sentri-analytics/docs/adr/0004-hosting-modernization-scope.md`). sentri-analytics is a **read-only** dashboard on the Aurora cluster this repo owns. This file lists the changes **aquilla-main** must make so the new compute can reach Aurora, plus the coordination items around credentials and decommissioning.

aquilla-main owns: the Aurora VPC, the Aurora cluster, its `DBSecurityGroup`, the Aurora-side route tables, and the DB credentials. sentri-analytics cannot grant itself access to any of these — that is why these changes live here.

## TL;DR — what must change here

1. **Codify the existing (drifted) connectivity** into `template.yaml` before anything else.
2. **Add an Aurora-side return route** to the sentri-analytics app VPC over the peering connection.
3. **Add Aurora `DBSecurityGroup` ingress** on 5432 for the sentri-analytics app VPC CIDR.
4. **Provide a stable read credential** (ideally a dedicated read-only role) and coordinate any rotation.

Nothing about the device ingest pipeline (API Gateway, Lambdas, SQS, S3, mTLS) changes. This is purely the database-access path for an internal reader.

## Verified topology (account 867958227555, us-east-2)

| | Aurora VPC (this repo) | sentri-analytics app VPC |
|---|---|---|
| VPC | `vpc-0031b6ad2eac1ae9f` (SAM `SentriVPC`) | new per-env VPC (`SentriVpcStack`) |
| CIDR | `10.0.0.0/16` | `10.1.0.0/16` |
| Subnets | `10.0.1.0/24` (2a), `10.0.2.0/24` (2b), isolated | public + private-with-egress |
| Route table | `rtb-076d091c4bfd764c7` | own |
| Aurora SG | `DBSecurityGroup` — **allows only `LambdaSecurityGroup`** (`template.yaml:106-115`) | — |

Same account + same region ⇒ the VPC peering connection (created on the sentri-analytics side) **auto-accepts**; no manual acceptance step. The required work is the **return route** and the **SG ingress** on this side.

## Step 0 (do first): resolve the connectivity drift

The deployed Aurora currently accepts connections from the existing sentri-analytics EC2 (`10.1.x`), but `template.yaml` contains **no peering, no route to `10.1.0.0/16`, and no SG rule for it**. Those were added out-of-band in the console. Risk: the next `sam deploy` can revert them and break **both** the current EC2 and the new ASG.

- [ ] Inspect the live Aurora VPC: confirm the peering connection ID (`pcx-…`), the route on `rtb-076d091c4bfd764c7` to `10.1.0.0/16`, and the `DBSecurityGroup` rule that actually admits the current EC2.
- [ ] Bring those into `template.yaml` (below) so they are managed, not drifted.

## Required changes

### 1. Aurora-side return route to the sentri-analytics VPC

Peering routes are not symmetric — sentri-analytics adds the route on its side; Aurora must add the return route or replies never get back.

```yaml
# template.yaml — Aurora VPC route table
SentriAnalyticsPeeringRoute:
  Type: AWS::EC2::Route
  Properties:
    RouteTableId: !Ref PrivateRouteTable        # deployed: rtb-076d091c4bfd764c7
    DestinationCidrBlock: !Ref SentriAnalyticsVpcCidr   # 10.1.0.0/16 (prod)
    VpcPeeringConnectionId: !Ref SentriAnalyticsPeeringId
```

`SentriAnalyticsPeeringId` and the CIDR come from the sentri-analytics CDK output `PeeringConnectionId` (`sentri-vpc-stack.ts:43`). Pass them in as SAM parameters — this is the cross-stack handshake.

### 2. Aurora `DBSecurityGroup` ingress for the dashboard

Currently only the ingest Lambda SG is allowed. Add the reader. Use the **CIDR** form — cross-VPC security-group references over peering are brittle; the CIDR rule is robust and matches the parallel-run requirement.

```yaml
# template.yaml — DBSecurityGroup.SecurityGroupIngress (add alongside the existing Lambda rule)
- IpProtocol: tcp
  FromPort: 5432
  ToPort: 5432
  CidrIp: !Ref SentriAnalyticsVpcCidr           # 10.1.0.0/16
  Description: sentri-analytics dashboard (read-only) over VPC peering
```

Keep the existing `LambdaSecurityGroup` ingress untouched.

### 3. Per-environment

sentri-analytics intends separate dev and prod app VPCs. Each gets its own non-overlapping CIDR (e.g. prod `10.1.0.0/16`, dev `10.2.0.0/16`) and therefore its own return route + ingress rule + peering. Parameterize so the dev and prod SAM stacks each admit only their matching sentri-analytics VPC.

### 4. Read credential (coordination — see also rotation below)

sentri-analytics fetches `sentri/db` from Secrets Manager and connects with `DATABASE_SSL=true`. Aurora keeps requiring TLS (`require`) — no change. **Recommended:** instead of sharing the Aurora master credential, provision a dedicated least-privilege role via the existing `schema_runner` Lambda:

```sql
CREATE ROLE sentri_readonly LOGIN PASSWORD '<from secret>';
GRANT CONNECT ON DATABASE sentri TO sentri_readonly;
GRANT USAGE ON SCHEMA public TO sentri_readonly;
GRANT SELECT ON devices, runs, run_results TO sentri_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON device_sites TO sentri_readonly;  -- device_sites is owned by sentri-analytics
```

This makes credential rotation independent of the pipeline and enforces the read-only contract at the database, not just by convention.

## Coordination items (timeline)

- **Parallel run:** keep BOTH the old EC2 access and the new ASG VPC access on Aurora at the same time. Do not remove the old EC2's route/SG rule until sentri-analytics Phase E.
- **Credential rotation (sentri-analytics Phase D):** the old `setup.sh` path leaked the DB credential via SSM/CloudTrail, so it will be rotated. **If sentri-analytics and the pipeline share a credential, rotating it will break `aurora_loader` (Lambda 3) unless its secret/`DB_DSN` is updated in the same change.** The dedicated read-only role above avoids this coupling entirely — strongly preferred.
- **Decommission (sentri-analytics Phase E):** when the old EC2 is torn down, remove its now-stale route/SG ingress rule from the Aurora side too.

## Optional hardening

- [ ] Bump `AuroraCluster.BackupRetentionPeriod` (currently 7 days, `template.yaml`) before gated migrations, so PITR covers a "would we notice a bad migration" window.
- [ ] Add the read-only role + grants to the `schema_runner` migration set so it is reproducible.

## What aquilla-main does NOT need to do

- No changes to API Gateway, the three ingest Lambdas, SQS, S3, or the device payload.
- No mTLS / PKI / truststore work (that is a separate ingest-tier decision; see `sentri-analytics/docs/AnalyticsInfrastrucure/ingest-architecture-tradeoff.md`).
- No schema changes to `devices`/`runs`/`run_results` for the hosting move. (Those are only needed for *new dashboard features* — firmware version, telemetry, etc. — which are out of scope here.)

## Acceptance check

From a new sentri-analytics ASG instance (in `10.1.0.0/16`), `psql "$DATABASE_URL"` connects over TLS and `SELECT count(*) FROM runs;` returns — while the device ingest pipeline continues writing normally, and the rule survives a `sam deploy` (no drift).
