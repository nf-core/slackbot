"""DynamoDB client initialisation and local dev table creation.

In production the table is created by CloudFormation.
For local dev, ``ensure_table()`` creates it against DynamoDB Local.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table

logger = logging.getLogger(__name__)

# Module-level singleton — initialised by ``get_table()``.
_table: Table | None = None


def _resource(*, endpoint_url: str | None, region: str) -> DynamoDBServiceResource:
    if endpoint_url:
        return boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint_url)
    return boto3.resource("dynamodb", region_name=region)


def ensure_table(
    *,
    table_name: str,
    endpoint_url: str | None,
    region: str,
) -> Table:
    """Return the DynamoDB ``Table``, creating it first when running locally.

    The table schema follows the single-table design described in the README:

    * PK / SK  — partition and sort key (String)
    * GSI1PK / GSI1SK — Global Secondary Index for site-scoped queries
    """
    dynamo = _resource(endpoint_url=endpoint_url, region=region)

    try:
        table = dynamo.Table(table_name)
        table.load()
        logger.info("DynamoDB table '%s' already exists.", table_name)
        return table
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    logger.info("Creating DynamoDB table '%s' (local dev) …", table_name)
    table = dynamo.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 5,
                    "WriteCapacityUnits": 5,
                },
            }
        ],
        ProvisionedThroughput={
            "ReadCapacityUnits": 5,
            "WriteCapacityUnits": 5,
        },
    )
    table.wait_until_exists()
    logger.info("Table '%s' created.", table_name)
    return table


def get_table() -> Table:
    """Return the cached table reference.

    Call ``init()`` at app startup to configure the table before first use.
    """
    if _table is None:
        raise RuntimeError("DynamoDB table not initialised — call db.client.init() first")
    return _table


def init(*, table_name: str, endpoint_url: str | None, region: str) -> None:
    """Bootstrap the module-level table reference (called once at startup)."""
    global _table  # noqa: PLW0603
    _table = ensure_table(table_name=table_name, endpoint_url=endpoint_url, region=region)
