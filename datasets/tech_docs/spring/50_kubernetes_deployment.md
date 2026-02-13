# Kubernetes Deployment

Kubernetes, often abbreviated as K8s, is a powerful open-source platform for managing containerized workloads and services. At the heart of Kubernetes lies the **Deployment** resource, which provides declarative updates for Pods and ReplicaSets. This document explores Kubernetes Deployments and related concepts such as Services, ConfigMaps, Secrets, and health checks, with a focus on production-grade best practices and real-world use cases.

---

## Deployment: The Core of Application Lifecycle Management

A Kubernetes Deployment is a higher-level abstraction that manages the deployment and scaling of your application. It ensures that a specified number of Pod replicas are running at any given time and facilitates rolling updates with rollback capabilities.

### Key Use Cases:
- **Rolling deployments** to minimize downtime
- **Canary deployments** for gradual feature rollouts
- **Blue/green deployments** for zero-downtime updates
- **Rollbacks** in case of failed deployments
- **Scaling** based on metrics or predefined rules

A typical Deployment manifest looks like this:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: springboot-deployment
  labels:
    app: springboot
spec:
  replicas: 3
  selector:
    matchLabels:
      app: springboot
  template:
    metadata:
      labels:
        app: springboot
    spec:
      containers:
      - name: springboot-app
        image: my-registry/springboot-app:latest
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: app-config
        - secretRef:
            name: app-secrets
        livenessProbe:
          httpGet:
            path: /actuator/health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        readinessProbe:
          httpGet:
            path: /actuator/health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
```

In this example:
- The `replicas` field ensures that three instances of the application are always running.
- The `envFrom` section references ConfigMaps and Secrets to inject configuration.
- `livenessProbe` and `readinessProbe` ensure the health of the application at runtime.

---

## Deployment Strategies

### Rolling Update (Default Strategy)
This strategy gradually replaces old Pods with new ones. It is the default strategy in Kubernetes. Here’s an example of how to configure it in your Deployment:

```yaml
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 25%
      maxSurge: 25%
```

- **`maxUnavailable`**: Ensures no more than 25% of the total replicas are unavailable during the update.
- **`maxSurge`**: Limits the number of Pods that can be created beyond the desired total.

### Canary Deployment
Canary deployments involve gradually shifting traffic to a new version of the application. While Kubernetes doesn’t natively support canary deployments, tools like **Istio**, **Flagger**, or **Argo Rollouts** can help manage this.

Example using Istio with virtual services:

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: canary-vs
spec:
  hosts:
  - "myapp.example.com"
  gateways:
  - public-gateway
  http:
  - route:
    - destination:
        host: canary
        subset: v2
      weight: 20
    - destination:
        host: canary
        subset: v1
      weight: 80
```

This configuration directs 20% of traffic to the new version (`v2`) and 80% to the current version (`v1`).

---

## Services: Exposing Your Application

A Kubernetes Service is an abstraction that defines a logical set of Pods and a policy to access them. It decouples the application from the underlying infrastructure.

### ClusterIP Service (Default)
This is the default service type, which allows internal access within the cluster:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: springboot-service
spec:
  type: ClusterIP
  selector:
    app: springboot
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
```

### LoadBalancer Service (Production Use)
For external access, the LoadBalancer service type is commonly used in cloud environments like AWS, GCP, or Azure:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: springboot-lb
spec:
  type: LoadBalancer
  selector:
    app: springboot
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
```

### Ingress for HTTP Routing
Ingress allows routing HTTP traffic to services based on the URL path or hostname:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: springboot-ingress
spec:
  rules:
  - http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: springboot-service
            port:
              number: 80
```

---

## ConfigMaps and Secrets: Configuration and Sensitive Data

### ConfigMap
Use ConfigMaps to store non-sensitive configuration data, such as environment-specific settings:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  spring.datasource.url: jdbc:mysql://db-service:3306/appdb
  spring.datasource.username: appuser
```

### Secret
Secrets are used for storing sensitive data like passwords, API keys, or tokens:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
type: Opaque
data:
  spring.datasource.password: YWRtaW4=  # base64 encoded
```

Injecting these into a Pod:

```yaml
envFrom:
- configMapRef:
    name: app-config
- secretRef:
    name: app-secrets
```

> ⚠️ **Best Practice**: Always use Secrets for sensitive data and avoid hardcoding credentials in code or manifests.

---

## Health Checks: Liveness and Readiness Probes

Health checks are crucial for ensuring that your application is running and ready to serve traffic.

### Liveness Probe
Detects when a container is stuck or in an unrecoverable state:

```yaml
livenessProbe:
  httpGet:
    path: /actuator/health
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 10
```

### Readiness Probe
Determines when a container is ready to receive traffic:

```yaml
readinessProbe:
  httpGet:
    path: /actuator/health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

> ✅ **Tip**: Use Spring Boot Actuator (`/actuator/health`) for accurate health checking in Spring applications (see [Deployment (49)]).

---

## Best Practices

### Use Declarative Configuration
Always use YAML manifests to define your resources. Avoid using `kubectl run` for production deployments as it creates imperative objects that are difficult to track.

### Auto-scaling with HPA
Horizontal Pod Autoscaler (HPA) dynamically scales the number of Pods based on CPU or custom metrics:

```yaml
apiVersion: autoscaling/v2beta2
kind: HorizontalPodAutoscaler
metadata:
  name: springboot-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: springboot-deployment
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Immutable Infrastructure
Treat your Kubernetes manifests as code. Store them in version control and use CI/CD pipelines to apply changes.

### Labeling and Namespacing
Use labels to organize and select resources effectively. Namespaces help isolate different environments (e.g., dev, staging, prod).

---

## Cross-Platform Considerations

### Spring Boot Actuator Integration (Actuator 25)
Spring Boot Actuator provides built-in health, metrics, and info endpoints that integrate seamlessly with Kubernetes probes. Ensure your application exposes `/actuator/health` and is secured appropriately in production.

Example Actuator health check:

```yaml
readinessProbe:
  httpGet:
    path: /actuator/health
    port: 8080
```

> 🔐 **Security Tip**: Secure `/actuator/**` endpoints using Spring Security in production.

---

## Common Pitfalls and Troubleshooting

### Pod Not Starting
Check the logs using:

```bash
kubectl logs <pod-name>
```

Also inspect the Events in the pod description:

```bash
kubectl describe pod <pod-name>
```

### Deployment Stuck in Pending
Ensure that:
- Node resources are available.
- PersistentVolumeClaims are bound.
- Image pull secrets are configured correctly.

### Service Not Accessible
Check:
- The service selector matches the Pod labels.
- The endpoint exists using `kubectl get endpoints <service-name>`.
- Ingress or LoadBalancer is correctly configured.

---

## Real-World Use Case: Spring Boot Application in Production

Consider a Spring Boot application that uses a MySQL database, is secured with SSL, and has Actuator endpoints for health checks. Below is a simplified deployment setup:

**Deployment (Spring Boot App)**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: springboot-prod
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: springboot
    spec:
      containers:
      - name: app
        image: my-registry/springboot:latest
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: app-config
        - secretRef:
            name: app-secrets
        livenessProbe:
          httpGet:
            path: /actuator/health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        readinessProbe:
          httpGet:
            path: /actuator/health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
```

**ConfigMap**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  spring.datasource.url: jdbc:mysql://mysql-service:3306/appdb
```

**Secret**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
type: Opaque
data:
  spring.datasource.password: YWRtaW4=
```

**Service**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: springboot-service
spec:
  type: ClusterIP
  selector:
    app: springboot
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
```

**Ingress**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: springboot-ingress
spec:
  rules:
  - http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: springboot-service
            port:
              number: 80
```

This setup ensures secure, scalable, and highly available deployment of a Spring Boot application in a Kubernetes cluster.

---

## Conclusion

Kubernetes Deployments provide a robust mechanism for managing application deployments in production environments. By leveraging Services, ConfigMaps, Secrets, and health checks, you can build resilient and scalable systems. Integrating with tools like Spring Actuator enables precise health monitoring and automated recovery.

Understanding the nuances of deployment strategies, health checks, and configuration management is essential for senior engineers aiming to build production-grade systems. Always follow best practices, use declarative configuration, and monitor your applications actively to maintain high availability and performance.