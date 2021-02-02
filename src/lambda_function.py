import boto3
import logging
import os

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CODEPIPELINE_CLIENT = boto3.client('codepipeline')

ARTIFACT_BUCKET = os.environ['artifact_bucket_name']
IAM_ROLE_ARN = os.environ['codepipeline_iam_role_arn']
PROJECT_NAME = os.environ['codebuild_project_name']

def lambda_handler(event, context):
    record = event['Records'][0]
    event_name = record['eventName']
    codecommit_repo_name = record['eventSourceARN'].split(':')[-1]

    reference = record['codecommit']['references'][0]
    if "tags" not in reference['ref']:
        branch_name = reference['ref'].replace('refs/heads/', '')

        if branch_name != "master":
            # Check if a Pipeline exits for this branch
            pipeline_exists = False
            pipelines = None

            # Here, I appreviate the repo name, you may need to change how this is done
            # to match your naming convention
            repo_name_abbrv = (codecommit_repo_name.split('-')[-1]).capitalize()
            pipeline_name = (f"{repo_name_abbrv}_{branch_name}")
            pipeline_name = pipeline_name.replace('/', '_')

            try:
                pipelines = CODEPIPELINE_CLIENT.list_pipelines()
            except ClientError as e:
                logger.error("Error Listing Pipelines: %s" % e)

            if pipeline_name in [pipeline['name'] for pipeline in pipelines['pipelines']]:
                logger.info(f"Pipeline `{pipeline_name}` exists")
                pipeline_exists = True

            # If branch deleted and pipeline exists, delete pipeline
            if reference.get('deleted', False):
                logger.info(f"Branch `{branch_name}` deleted")
                if pipeline_exists:
                    logger.info(f"Deleting Pipeline `{pipeline_name}`")
                    delete_codepipeline(pipeline_name)

            # If new commit on branch and no pipeline exists, create pipeline
            elif event_name in ['ReferenceChanges']:
                logger.info(f"New commit on branch `{branch_name}`")
                if not pipeline_exists:
                    logger.info(f"Creating Terraform Pipeline for `{branch_name}` called `{pipeline_name}`")
                    create_codepipeline(branch_name, codecommit_repo_name, pipeline_name, PROJECT_NAME)


def delete_codepipeline(pipeline_name):
    try:
        CODEPIPELINE_CLIENT.delete_pipeline(name=pipeline_name)
    except ClientError as e:
        logger.error("Error Deleting Pipeline: %s" % e)


def create_codepipeline(branch_name, codecommit_repo_name, pipeline_name, project_name):
    stage_name = "Terraform_Plan"

    try:
        CODEPIPELINE_CLIENT.create_pipeline(
            pipeline={
                'name': pipeline_name,
                'roleArn': IAM_ROLE_ARN,
                'artifactStore': {
                    'type': 'S3',
                    'location': ARTIFACT_BUCKET,
                },
                'stages': [
                    {
                        'name': 'Source',
                        'actions': [{
                            'name': 'Source',
                            'actionTypeId': {
                                'category': 'Source',
                                'owner': 'AWS',
                                'provider': 'CodeCommit',
                                'version': '1'
                            },
                            'outputArtifacts': [{
                                    'name': 'SourceArtifact'
                                }],
                            'configuration': {
                                'RepositoryName': codecommit_repo_name,
                                'BranchName': branch_name
                            }
                        }]
                    }, {
                        'name': 'Terraform_Plan',
                        'actions': [{
                            'name': 'Terraform_Plan',
                            'actionTypeId': {
                                'category': 'Build',
                                'owner': 'AWS',
                                'provider': 'CodeBuild',
                                'version': '1'
                            },
                            'inputArtifacts': [{
                                'name': 'SourceArtifact'
                            }],
                            'configuration': {
                                'ProjectName': project_name,
                            }
                        }]
                    }
                ]
            }
        )
    except ClientError as e:
        logger.error("Error Creating Terraform Pipeline: %s" % e)
