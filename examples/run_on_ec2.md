# End-to-end: extract on EC2, tear down cleanly

Everything below is read-only against Hyperliquid's buckets. The only resources you
create are your own output bucket, an IAM role, and one instance — all removed at the
end.

Total cost for the full ~211 GB fills extract: **under $1**.

## 0. Prerequisites

```bash
aws configure          # region: ap-northeast-1  (same region as the archives)
aws sts get-caller-identity
```

Use an **IAM user scoped to S3 read**, not root. Root keys can't be scoped and a typo
has your whole account as its blast radius. `aws login` (SSO) is fine too.

## 1. Output bucket + role

```bash
export ACCT=$(aws sts get-caller-identity --query Account --output text)
export BUCKET="hlx-extract-$ACCT"

aws s3api create-bucket --bucket "$BUCKET" --region ap-northeast-1 \
  --create-bucket-configuration LocationConstraint=ap-northeast-1

cat > /tmp/trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
aws iam create-role --role-name hlx-role \
  --assume-role-policy-document file:///tmp/trust.json

cat > /tmp/policy.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],
  "Resource":["arn:aws:s3:::hl-mainnet-node-data","arn:aws:s3:::hl-mainnet-node-data/*"]},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:ListBucket"],
  "Resource":["arn:aws:s3:::$BUCKET","arn:aws:s3:::$BUCKET/*"]}]}
EOF
aws iam put-role-policy --role-name hlx-role --policy-name hlx --policy-document file:///tmp/policy.json
aws iam create-instance-profile --instance-profile-name hlx-profile
aws iam add-role-to-instance-profile --instance-profile-name hlx-profile --role-name hlx-role
```

> **Grant `s3:GetObject` on your *own* bucket too.** With only `PutObject` the instance
> can upload its log but cannot download its own script — a 403 that looks like a code
> bug. IAM changes also take a few seconds to propagate; retry the first fetch.

## 2. Launch (self-terminating)

```bash
aws s3 cp src/hlarchive/liquidations.py "s3://$BUCKET/job.py"
AMI=$(aws ssm get-parameters --names \
  /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)

cat > /tmp/userdata.sh <<EOF
#!/bin/bash
shutdown -h +170 &          # hard cost guard: die after 170 min no matter what
exec > /var/log/hlx.log 2>&1
set -x
dnf install -y python3-pip >/dev/null 2>&1
pip3 install --quiet boto3 lz4
for i in 1 2 3 4 5; do aws s3 cp s3://$BUCKET/job.py /tmp/job.py && break; sleep 10; done
python3 /tmp/job.py --out /tmp/liq.jsonl.gz --upload-bucket $BUCKET
aws s3 cp /var/log/hlx.log s3://$BUCKET/run.log
shutdown -h now
EOF

aws ec2 run-instances --image-id "$AMI" --instance-type m7i-flex.large \
  --iam-instance-profile Name=hlx-profile \
  --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}' \
  --user-data file:///tmp/userdata.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=hlx}]' \
  --query 'Instances[0].InstanceId' --output text
```

Three cost guards, all worth keeping:
`instance-initiated-shutdown-behavior=terminate` (script ends → instance dies),
`shutdown -h +170` (hangs die anyway), `DeleteOnTermination=true` (no orphan volume).

New AWS accounts are restricted to **free-tier instance types** — larger types are
refused outright. `m7i-flex.large` is the best available and sustains ~4.2 GB/min.

## 3. Watch

```bash
aws s3 ls "s3://$BUCKET/liq/"                    # appears at the end
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name NetworkIn \
  --dimensions Name=InstanceId,Value=$IID --period 300 --statistics Sum \
  --start-time $(date -u -v-3H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --query 'Datapoints[].Sum'
```

Sustained CPU/NetworkIn is your progress bar. A run that dies in the first minute at
~0% CPU is a setup failure (IAM, deps), not a slow job — check `run.log`.

## 4. Collect and tear down

```bash
aws s3 cp "s3://$BUCKET/liq/liquidations.jsonl.gz" .

aws s3 rm "s3://$BUCKET" --recursive && aws s3api delete-bucket --bucket "$BUCKET"
aws iam remove-role-from-instance-profile --instance-profile-name hlx-profile --role-name hlx-role
aws iam delete-instance-profile --instance-profile-name hlx-profile
aws iam delete-role-policy --role-name hlx-role --policy-name hlx
aws iam delete-role --role-name hlx-role

# verify nothing is left billing
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running,pending,stopped" \
  --query 'length(Reservations[].Instances[])'
aws ec2 describe-volumes --query 'length(Volumes)'
```

Verify the teardown rather than assuming it. A forgotten volume bills quietly forever.

## 5. Sanity-check the result

Cross-check against an independent source if one exists, matching only comparable rows.
Agreement on trade IDs across two independently-built pipelines validates both; a
row-count ratio that differs is usually a **convention** difference (e.g. per-leg rows
vs deduped trades), not an error — confirm which before "fixing" anything.
