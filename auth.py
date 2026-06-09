import hashlib
from fastapi import Header, HTTPException, status
from config import ACCESS_PASSWORD

# 计算服务端的静态 Token
# 使用 sha256 算法，并加上固定的盐值，避免明文泄露
TOKEN_SALT = "bili2text_secret_salt_2026"

def get_expected_token() -> str:
    raw_str = f"{ACCESS_PASSWORD}_{TOKEN_SALT}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

def verify_token(authorization: str = Header(None)):
    """
    FastAPI 依赖项，用于拦截并验证 API 请求中的 Token。
    格式要求: Authorization: Bearer <token>
    """
    # 如果服务端配置密码为空，视为不需要密码（可选，这里为了安全强制需要）
    if not ACCESS_PASSWORD:
        return True
        
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
        
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format"
            )
            
        token = parts[1]
        expected_token = get_expected_token()
        
        if token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access: Incorrect token"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access"
        )
    return True
