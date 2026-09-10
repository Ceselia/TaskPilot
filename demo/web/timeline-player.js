"/"
 * 时间轴回放引擎：从 timeline.json 驱动前端 UI
 * 
 * 功能：
 * - 加载 timeline.json
 * - 按时间轴回放事件
 * - 用户交互触发对应事件段
 * - 暂停/继续/加速控制
 */

class TimelinePlayer {
    constructor(timelineUrl = 'data/timeline.json') {
        this.timeline = null;
        this.events = [];
        this.currentEventIndex = 0;
        this.isPlaying = false;
        this.isPaused = false;
        this.playbackSpeed = 1.0;
        this.eventHandlers = {};
        this.timelineUrl = timelineUrl;
    }

    /**
     * 加载 timeline.json 文件
     */
    async load() {
        try {
            const response = await fetch(this.timelineUrl);
            this.timeline = await response.json();
            this.events = this.timeline.events || [];
            console.log(`✅ Timeline loaded: ${this.events.length} events`);
            return true;
        } catch (error) {
            console.error('❌ Failed to load timeline:', error);
            return false;
        }
    }

    /**
     * 注册事件处理器
     */
    on(eventType, handler) {
        if (!this.eventHandlers[eventType]) {
            this.eventHandlers[eventType] = [];
        }
        this.eventHandlers[eventType].push(handler);
    }

    /**
     * 触发事件处理器
     */
    emit(eventType, data) {
        if (this.eventHandlers[eventType]) {
            this.eventHandlers[eventType].forEach(handler => {
                try {
                    handler(data);
                } catch (e) {
                    console.error(`Error in ${eventType} handler:`, e);
                }
            });
        }
    }

    /**
     * 开始回放
     */
    async play() {
        if (this.isPlaying) return;
        
        this.isPlaying = true;
        this.isPaused = false;
        this.emit('playStart', {});

        while (this.currentEventIndex < this.events.length) {
            if (this.isPaused) {
                await new Promise(resolve => {
                    const checkInterval = setInterval(() => {
                        if (!this.isPaused) {
                            clearInterval(checkInterval);
                            resolve();
                        }
                    }, 100);
                });
            }

            const currentEvent = this.events[this.currentEventIndex];
            const nextEvent = this.events[this.currentEventIndex + 1];
            
            // 计算延迟时间
            let delayMs = 0;
            if (nextEvent) {
                delayMs = (nextEvent.timestamp - currentEvent.timestamp) / this.playbackSpeed;
            }

            // 处理当前事件
            await this.processEvent(currentEvent);
            this.currentEventIndex++;

            // 等待下一事件
            if (delayMs > 0) {
                await this.wait(delayMs);
            }
        }

        this.isPlaying = false;
        this.emit('playEnd', { totalEvents: this.events.length });
    }

    /**
     * 处理单个事件
     */
    async processEvent(event) {
        const { type, data } = event;
        
        // 根据事件类型调用相应处理器
        this.emit('event', { type, data });
        this.emit(type, data);

        console.log(`[${event.timestamp}ms] ${type}:`, data);
    }

    /**
     * 暂停回放
     */
    pause() {
        this.isPaused = true;
        this.emit('pause', { currentIndex: this.currentEventIndex });
    }

    /**
     * 继续回放
     */
    resume() {
        this.isPaused = false;
        this.emit('resume', { currentIndex: this.currentEventIndex });
    }

    /**
     * 跳转到指定事件
     */
    jumpToEvent(index) {
        this.currentEventIndex = Math.max(0, Math.min(index, this.events.length - 1));
        this.emit('jump', { currentIndex: this.currentEventIndex });
    }

    /**
     * 跳转到指定阶段
     */
    jumpToPhase(phaseName) {
        const phases = this.timeline.phase_transitions || [];
        const phase = phases.find(p => p.phase === phaseName);
        
        if (phase) {
            // 找到最接近该时间戳的事件
            const index = this.events.findIndex(e => e.timestamp >= phase.timestamp);
            if (index >= 0) {
                this.jumpToEvent(index);
                return true;
            }
        }
        return false;
    }

    /**
     * 设置回放速度
     */
    setSpeed(speed) {
        this.playbackSpeed = Math.max(0.1, speed);
        this.emit('speedChange', { speed: this.playbackSpeed });
    }

    /**
     * 获取当前阶段
     */
    getCurrentPhase() {
        if (!this.events[this.currentEventIndex]) return null;
        
        const currentTime = this.events[this.currentEventIndex].timestamp;
        const phases = this.timeline.phase_transitions || [];
        
        // 找到最接近但不超过当前时间的阶段
        let currentPhase = null;
        for (let phase of phases) {
            if (phase.timestamp <= currentTime) {
                currentPhase = phase;
            } else {
                break;
            }
        }
        
        return currentPhase;
    }

    /**
     * 获取进度百分比
     */
    getProgress() {
        return this.events.length > 0 
            ? (this.currentEventIndex / this.events.length) * 100
            : 0;
    }

    /**
     * 等待指定毫秒数
     */
    wait(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * 重置回放
     */
    reset() {
        this.currentEventIndex = 0;
        this.isPlaying = false;
        this.isPaused = false;
        this.emit('reset', {});
    }
}

export { TimelinePlayer };
