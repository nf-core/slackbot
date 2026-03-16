#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.bot_stack import NfCoreBotStack

app = cdk.App()
NfCoreBotStack(
    app,
    "NfCoreBotStack",
    env=cdk.Environment(account="728131696474", region="eu-west-1"),
)
app.synth()
