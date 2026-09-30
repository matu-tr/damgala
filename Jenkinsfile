pipeline {
    agent { label 'docker' }

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        IMAGE = 'ghcr.io/matu-tr/damgala'
    }

    stages {
        // main: prove the image still builds. Tags (v*.*.*): build, push, release.
        stage('Build image') {
            steps {
                sh 'docker build --pull -t "$IMAGE:ci-$BUILD_TAG" .'
            }
        }

        stage('Verify tag format') {
            when { buildingTag() }
            steps {
                sh '''
                    echo "$TAG_NAME" | grep -Eq '^v[0-9]+\\.[0-9]+\\.[0-9]+$' || {
                        echo "Tag $TAG_NAME is not vX.Y.Z"; exit 1; }
                '''
            }
        }

        stage('Push to GHCR') {
            when { buildingTag() }
            steps {
                withCredentials([usernamePassword(credentialsId: 'ghcr-matu-tr',
                        usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                    // A per-build DOCKER_CONFIG keeps the registry login off the shared agent.
                    sh '''
                        export DOCKER_CONFIG="$WORKSPACE_TMP/docker"
                        mkdir -p "$DOCKER_CONFIG"
                        echo "$GH_TOKEN" | docker login ghcr.io -u "$GH_USER" --password-stdin
                        for tag in "$TAG_NAME" latest; do
                            docker tag "$IMAGE:ci-$BUILD_TAG" "$IMAGE:$tag"
                            docker push "$IMAGE:$tag"
                        done
                        docker logout ghcr.io
                    '''
                }
            }
        }

        stage('GitHub release') {
            when { buildingTag() }
            steps {
                withCredentials([usernamePassword(credentialsId: 'ghcr-matu-tr',
                        usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
                    sh '''
                        curl -fsS -X POST \
                            -H "Authorization: Bearer $GH_TOKEN" \
                            -H "Accept: application/vnd.github+json" \
                            https://api.github.com/repos/matu-tr/damgala/releases \
                            -d "{\\"tag_name\\":\\"$TAG_NAME\\",\\"generate_release_notes\\":true}" \
                            -o /dev/null
                    '''
                }
            }
        }
    }

    post {
        // The agent shares the host's Docker daemon; leave no tags of ours behind.
        always {
            sh '''
                docker image rm "$IMAGE:ci-$BUILD_TAG" >/dev/null 2>&1 || true
                if [ -n "$TAG_NAME" ]; then
                    docker image rm "$IMAGE:$TAG_NAME" "$IMAGE:latest" >/dev/null 2>&1 || true
                fi
            '''
        }
    }
}
