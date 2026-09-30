pipeline {
    agent { label 'docker' }

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        // Built straight into the TrueNAS host's Docker (the agent shares its daemon);
        // nothing is pushed to a registry.
        IMAGE = 'local/damgala'
        KEEP_VERSIONS = '3'
    }

    stages {
        // main: prove the image still builds. Tags (vX.Y.Z): keep it as :vX.Y.Z and :latest.
        stage('Build image') {
            steps {
                sh 'docker build --pull -t "$IMAGE:ci-$BUILD_TAG" .'
            }
        }

        stage('Tag release image') {
            when { buildingTag() }
            steps {
                sh '''
                    echo "$TAG_NAME" | grep -Eq '^v[0-9]+\\.[0-9]+\\.[0-9]+$' || {
                        echo "Tag $TAG_NAME is not vX.Y.Z"; exit 1; }
                    docker tag "$IMAGE:ci-$BUILD_TAG" "$IMAGE:$TAG_NAME"
                    docker tag "$IMAGE:ci-$BUILD_TAG" "$IMAGE:latest"
                '''
            }
        }

        // Keeps the newest few version tags for rollback; older ones are untagged.
        stage('Prune old versions') {
            when { buildingTag() }
            steps {
                sh '''
                    docker image ls "$IMAGE" --format '{{.Tag}}' \
                        | grep -E '^v[0-9]+\\.[0-9]+\\.[0-9]+$' \
                        | sort -V -r \
                        | tail -n +"$((KEEP_VERSIONS + 1))" \
                        | while read -r old; do docker image rm "$IMAGE:$old"; done
                '''
            }
        }
    }

    post {
        always {
            sh 'docker image rm "$IMAGE:ci-$BUILD_TAG" >/dev/null 2>&1 || true'
        }
    }
}
