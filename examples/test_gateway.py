"""
测试 OpenAI 格式的图像生成 API
验证 Gateway 是否能正确响应标准的 OpenAI /v1/images/generations 请求
"""
import requests
import json
import base64
from pathlib import Path

# Gateway 配置
GATEWAY_URL = "http://127.0.0.1:4981"
OUTPUT_DIR = Path("./output/api_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def test_text_to_image():
    """测试文生图"""
    print("\n" + "="*60)
    print("测试1: 文生图 (OpenAI /v1/images/generations 格式)")
    print("="*60)
    
    payload = {
        "prompt": "A cute red panda eating bamboo in a snowy forest",
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json"
    }
    
    print(f"请求: POST {GATEWAY_URL}/v1/images/generations")
    print(f"Prompt: {payload['prompt']}")
    
    try:
        response = requests.post(
            f"{GATEWAY_URL}/v1/images/generations",
            json=payload,
            timeout=90
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 成功生成 {len(data['data'])} 张图像")
            
            # 保存图像
            for idx, item in enumerate(data['data']):
                img_data = base64.b64decode(item['b64_json'])
                output_path = OUTPUT_DIR / f"test1_panda_{idx}.png"
                output_path.write_bytes(img_data)
                print(f"   已保存: {output_path} ({len(img_data)} bytes)")
            
            return True
        else:
            print(f"❌ 请求失败")
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error")
                print(f"错误信息: {error_msg}")
            except Exception:
                print(f"状态码: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

def test_health_endpoints():
    """测试健康检查端点"""
    print("\n" + "="*60)
    print("测试0: 健康检查端点")
    print("="*60)
    
    endpoints = [
        ("/", "根端点"),
        ("/healthz", "健康检查"),
        ("/readyz", "就绪检查"),
    ]
    
    for path, name in endpoints:
        try:
            response = requests.get(f"{GATEWAY_URL}{path}", timeout=5)
            print(f"✅ {name} ({path}): {response.status_code} - {response.json()}")
        except Exception as e:
            print(f"❌ {name} ({path}): {e}")

if __name__ == "__main__":
    print("\n🚀 开始测试 Gemini Image Gateway (OpenAI 兼容 API)")
    print(f"Gateway URL: {GATEWAY_URL}")
    
    # 1. 健康检查
    test_health_endpoints()
    
    # 2. 文生图
    success = test_text_to_image()
    
    print("\n" + "="*60)
    if success:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败")
    print("="*60)
