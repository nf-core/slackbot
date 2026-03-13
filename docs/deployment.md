# Deployment

The bot uses Slack's **Socket Mode**, which means it maintains an outbound WebSocket connection to Slack. There's no need for a public URL, load balancer, or ingress rules. You just need a process running somewhere that stays alive.

## Architecture

```
Slack <──WebSocket──> ECS Fargate (bot) ──> GitHub API
                                        ──> DynamoDB (for hackathon features)
```

## Deploying to AWS ECS Fargate

### Prerequisites

- AWS CLI configured with the `nf-core` profile (or equivalent credentials for the nf-core AWS account)
- Docker installed and running
- The four required secrets stored in SSM Parameter Store (see step 6 below)

### Current deployment

The bot is currently deployed in:
- **AWS Account:** `728131696474`
- **Region:** `eu-west-1`
- **AWS CLI profile:** `nf-core`
- **ECS Cluster:** `nf-core-bot`
- **ECS Service:** `nf-core-bot`
- **ECR Repo:** `728131696474.dkr.ecr.eu-west-1.amazonaws.com/nf-core-bot`

### 1. Build and push the Docker image

```bash
# Set your AWS account and region
AWS_ACCOUNT=728131696474
AWS_REGION=eu-west-1
AWS_PROFILE=nf-core
ECR_REPO=$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/nf-core-bot

# Authenticate Docker to ECR
aws --profile $AWS_PROFILE ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPO

# Build for linux/amd64 (Fargate) and push
docker build --platform linux/amd64 -t nf-core-bot .
docker tag nf-core-bot:latest $ECR_REPO:latest
docker push $ECR_REPO:latest
```

### 2. Create the ECS task definition

Create a file called `taskdef.json`:

```json
{
  "family": "nf-core-bot",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
      "executionRoleArn": "arn:aws:iam::728131696474:role/nf-core-bot-execution-role",
      "taskRoleArn": "arn:aws:iam::728131696474:role/nf-core-bot-task-role",
  "containerDefinitions": [
    {
      "name": "nf-core-bot",
      "image": "728131696474.dkr.ecr.eu-west-1.amazonaws.com/nf-core-bot:latest",
      "essential": true,
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/nf-core-bot",
          "awslogs-region": "eu-west-1",
          "awslogs-stream-prefix": "bot"
        }
      },
      "secrets": [
        {"name": "SLACK_BOT_TOKEN", "valueFrom": "arn:aws:ssm:eu-west-1:728131696474:parameter/nf-core-bot/SLACK_BOT_TOKEN"},
        {"name": "SLACK_SIGNING_SECRET", "valueFrom": "arn:aws:ssm:eu-west-1:728131696474:parameter/nf-core-bot/SLACK_SIGNING_SECRET"},
        {"name": "SLACK_APP_TOKEN", "valueFrom": "arn:aws:ssm:eu-west-1:728131696474:parameter/nf-core-bot/SLACK_APP_TOKEN"},
        {"name": "GITHUB_TOKEN", "valueFrom": "arn:aws:ssm:eu-west-1:728131696474:parameter/nf-core-bot/GITHUB_TOKEN"}
      ],
      "environment": [
        {"name": "GITHUB_ORG", "value": "nf-core"},
        {"name": "AWS_REGION", "value": "eu-west-1"},
        {"name": "DYNAMODB_TABLE", "value": "nf-core-bot"},
        {"name": "CORE_TEAM_USERGROUP_HANDLE", "value": "core-team"}
      ]
    }
  ]
}
```

Register it:

```bash
aws --profile nf-core ecs register-task-definition --cli-input-json file://taskdef.json
```

### 3. Create the ECS service

```bash
aws --profile nf-core --region eu-west-1 ecs create-service \
  --cluster nf-core-bot \
  --service-name nf-core-bot \
  --task-definition nf-core-bot \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-d8b49f90,subnet-fb58039d,subnet-f12743ab],securityGroups=[sg-076fdd2edb128eae4],assignPublicIp=ENABLED}"
```

Key points:
- **Desired count should be 1** — Socket Mode uses a single persistent connection. Running multiple instances would cause duplicate message handling.
- **No load balancer needed** — the bot connects outbound to Slack, no inbound traffic.
- **Public IP or NAT gateway** — the container needs outbound internet access to reach the Slack and GitHub APIs.

### 4. IAM permissions

The task role (`nf-core-bot-task-role`) needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:eu-west-1:728131696474:table/nf-core-bot",
        "arn:aws:dynamodb:eu-west-1:728131696474:table/nf-core-bot/index/*"
      ]
    }
  ]
}
```

The execution role needs `ssm:GetParameters` (or `secretsmanager:GetSecretValue`) to inject secrets, plus `logs:CreateLogStream` and `logs:PutLogEvents` for CloudWatch.

DynamoDB permissions are required for hackathon registration features. The table must exist before the bot starts (see DynamoDB setup below).

### 5. Create the DynamoDB table

The bot uses a single DynamoDB table with a Global Secondary Index:

```bash
aws --profile nf-core --region eu-west-1 dynamodb create-table \
  --table-name nf-core-bot \
  --attribute-definitions \
    AttributeName=PK,AttributeType=S \
    AttributeName=SK,AttributeType=S \
    AttributeName=GSI1PK,AttributeType=S \
    AttributeName=GSI1SK,AttributeType=S \
  --key-schema \
    AttributeName=PK,KeyType=HASH \
    AttributeName=SK,KeyType=RANGE \
  --global-secondary-indexes \
    '[{"IndexName":"GSI1","KeySchema":[{"AttributeName":"GSI1PK","KeyType":"HASH"},{"AttributeName":"GSI1SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]' \
  --billing-mode PAY_PER_REQUEST
```

The table stores hackathon metadata, sites, organisers, and registrations. See the README for the full key schema.

### 6. Store secrets in SSM Parameter Store

```bash
aws --profile nf-core --region eu-west-1 ssm put-parameter --name /nf-core-bot/SLACK_BOT_TOKEN --type SecureString --value "xoxb-..."
aws --profile nf-core --region eu-west-1 ssm put-parameter --name /nf-core-bot/SLACK_SIGNING_SECRET --type SecureString --value "..."
aws --profile nf-core --region eu-west-1 ssm put-parameter --name /nf-core-bot/SLACK_APP_TOKEN --type SecureString --value "xapp-..."
aws --profile nf-core --region eu-west-1 ssm put-parameter --name /nf-core-bot/GITHUB_TOKEN --type SecureString --value "github_pat_..."
```

## Updating the Bot

To deploy a new version:

```bash
docker build --platform linux/amd64 -t nf-core-bot .
docker tag nf-core-bot:latest $ECR_REPO:latest
docker push $ECR_REPO:latest
aws --profile nf-core --region eu-west-1 ecs update-service --cluster nf-core-bot --service nf-core-bot --force-new-deployment
```

## Monitoring

- **Logs**: CloudWatch Logs at `/ecs/nf-core-bot`
- **Health**: ECS service shows 1/1 running tasks. If the process crashes, Fargate will restart it automatically.
- **Socket Mode**: if the WebSocket disconnects, the Slack Bolt framework automatically reconnects.

## Cost

A single Fargate task running 24/7 with 0.25 vCPU / 512 MB costs roughly **$9-10/month** in eu-west-1. DynamoDB on-demand for the expected volume would add negligible cost.
