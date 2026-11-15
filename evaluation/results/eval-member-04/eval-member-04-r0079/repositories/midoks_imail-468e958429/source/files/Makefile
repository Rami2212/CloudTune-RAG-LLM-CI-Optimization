# Makefile for imail

VERSION := 0.0.19
APP_NAME := imail

# 构建时间
BUILD_TIME := $(shell date +"%Y-%m-%d %H:%M:%S")
# Git 提交哈希
BUILD_COMMIT := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# Go 构建选项
GO_LDFLAGS := -ldflags "-X 'github.com/midoks/imail/internal/conf.BuildTime=$(BUILD_TIME)' -X 'github.com/midoks/imail/internal/conf.BuildCommit=$(BUILD_COMMIT)'"
GO_MOD := -mod=mod

.PHONY: build

# 构建应用
build:
	@echo "Building $(APP_NAME) v$(VERSION)..."
	@echo "Build Time: $(BUILD_TIME)"
	@echo "Build Commit: $(BUILD_COMMIT)"
	go build $(GO_MOD) $(GO_LDFLAGS) -o $(APP_NAME) .

# 运行应用
run:
	@echo "Running $(APP_NAME)..."
	./$(APP_NAME) service

# 清理构建文件
clean:
	@echo "Cleaning..."
	rm -f $(APP_NAME)

# 安装应用
install:
	@echo "Installing $(APP_NAME)..."
	go install $(GO_LDFLAGS) .

# 测试构建信息
test-build-info:
	@echo "Testing build information..."
	@echo "Build Time: $(BUILD_TIME)"
	@echo "Build Commit: $(BUILD_COMMIT)"
	@echo "To verify build information, run the application and check the admin dashboard"
