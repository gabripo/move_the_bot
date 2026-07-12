import math

# Link lengths (meters):
#   L0 — base to shoulder (vertical offset)
#   L1 — upper arm (shoulder to elbow)
#   L2 — forearm (elbow to gripper)
L0 = 0.20
L1 = 0.25
L2 = 0.25


def inverse_kinematics(x, y, z):
    """3-DOF inverse kinematics for a planar arm with base rotation.

    Coordinate frame:  x=forward, y=left, z=up.
    Returns (theta1, theta2, theta3) in radians, or None if unreachable.

    The arm has three revolute joints:
        θ₁ (base_joint)    — rotation about the vertical Z axis.
        θ₂ (shoulder_joint) — pitch of the upper arm from vertical.
        θ₃ (elbow_joint)   — pitch of the forearm relative to the upper arm.

    Derivation
    ----------
    θ₁ = atan2(y, x)                        (1)

    The problem reduces to a 2-link planar arm in the vertical plane
    defined by θ₁.  In that plane the target is at distance
        r   = sqrt(x² + y²)                  (2)   horizontal reach
        zᵣ  = z - L₀                         (3)   height above shoulder
        d   = sqrt(r² + zᵣ²)                 (4)   straight-line distance

    Reachability is checked via the triangle inequality:
        |L₁ - L₂| ≤ d ≤ L₁ + L₂             (5)

    θ₃ is found from the law of cosines on the (L₁, L₂, d) triangle:
        d² = L₁² + L₂² - 2·L₁·L₂·cos(π - θ₃)
        d² = L₁² + L₂² + 2·L₁·L₂·cos(θ₃)
        cos θ₃ = (d² - L₁² - L₂²) / (2·L₁·L₂)   (6)
        θ₃ = acos(cos θ₃)                        (7)

    θ₂ is the shoulder angle from vertical needed so that the 2-link
    chain reaches (r, zᵣ).  The direction from shoulder to target is
        α = atan2(r, zᵣ)                         (8)

    The forearm's contribution to the endpoint position (relative to the
    upper-arm direction) is at angle β from the upper arm:
        β = atan2(L₂·sin θ₃, L₁ + L₂·cos θ₃)     (9)

    Then:
        θ₂ = α - β                               (10)
    """
    theta1 = math.atan2(y, x)

    r = math.sqrt(x ** 2 + y ** 2)
    z_r = z - L0
    d = math.sqrt(r ** 2 + z_r ** 2)

    if d > L1 + L2 or d < abs(L1 - L2):
        return None

    cos_theta3 = (d ** 2 - L1 ** 2 - L2 ** 2) / (2.0 * L1 * L2)
    cos_theta3 = max(-1.0, min(1.0, cos_theta3))
    theta3 = math.acos(cos_theta3)

    alpha = math.atan2(r, z_r)
    beta = math.atan2(L2 * math.sin(theta3), L1 + L2 * math.cos(theta3))
    theta2 = alpha - beta

    return (theta1, theta2, theta3)
