"""CDK stack for the nf-core Slack bot.

Deploys a Fargate service running in Socket Mode (outbound WebSocket only),
a DynamoDB table for hackathon/registration data, and wires up secrets
from SSM Parameter Store.
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    Tags,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_dynamodb as dynamodb,
    aws_ssm as ssm,
    aws_logs as logs,
)
from constructs import Construct


class NfCoreBotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        Tags.of(self).add("Project", "nf-core-bot")

        # ----------------------------------------------------------------------
        # VPC - public subnets only, no NAT gateway needed.
        # The bot uses Slack Socket Mode (outbound WebSocket), so it only
        # needs outbound internet access via an Internet Gateway.
        # ----------------------------------------------------------------------
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # ----------------------------------------------------------------------
        # DynamoDB - single-table design for hackathons, sites, registrations.
        # See README.md for the full key schema.
        # ----------------------------------------------------------------------
        table = dynamodb.Table(
            self,
            "Table",
            table_name="nf-core-bot",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI1 - used to query registrations by site
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(name="GSI1PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="GSI1SK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ----------------------------------------------------------------------
        # ECS Cluster
        # ----------------------------------------------------------------------
        cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name="nf-core-bot",
            vpc=vpc,
        )

        # ----------------------------------------------------------------------
        # Task Definition - 0.25 vCPU / 512 MB, Fargate
        # ----------------------------------------------------------------------
        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            cpu=256,
            memory_limit_mib=512,
        )

        # Look up pre-existing SSM SecureString parameters that hold secrets.
        # These are created manually (outside CDK) and referenced here.
        ssm_secret_names = [
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET",
            "SLACK_APP_TOKEN",
            "GITHUB_TOKEN",
        ]

        # CloudWatch log group for the container
        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name="/ecs/nf-core-bot",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Add the bot container to the task
        task_definition.add_container(
            "bot",
            image=ecs.ContainerImage.from_registry("ghcr.io/nf-core/nf-core-slackbot:latest"),
            # Secrets injected from SSM SecureString parameters
            secrets={
                name: ecs.Secret.from_ssm_parameter(
                    ssm.StringParameter.from_secure_string_parameter_attributes(
                        self,
                        f"SSM{name.replace('_', '')}",
                        parameter_name=f"/nf-core-bot/{name}",
                    )
                )
                for name in ssm_secret_names
            },
            # Plain-text environment variables
            environment={
                "GITHUB_ORG": "nf-core",
                "AWS_DEFAULT_REGION": "eu-west-1",
                "DYNAMODB_TABLE": "nf-core-bot",
                "CORE_TEAM_USERGROUP_HANDLE": "core-team",
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="bot",
                log_group=log_group,
            ),
        )

        # Grant the task role read/write access to the DynamoDB table
        table.grant_read_write_data(task_definition.task_role)

        # ----------------------------------------------------------------------
        # Fargate Service - single task, public IP for outbound internet.
        # No inbound traffic needed (Socket Mode is outbound-only).
        # ----------------------------------------------------------------------
        security_group = ec2.SecurityGroup(
            self,
            "ServiceSG",
            vpc=vpc,
            description="nf-core-bot Fargate service - outbound only",
            allow_all_outbound=True,
        )

        service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            assign_public_ip=True,
            security_groups=[security_group],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=0,
            max_healthy_percent=100,
        )

        # ----------------------------------------------------------------------
        # Outputs
        # ----------------------------------------------------------------------
        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "ServiceName", value=service.service_name)
        CfnOutput(self, "TableName", value=table.table_name)
