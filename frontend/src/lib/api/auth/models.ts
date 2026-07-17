export class Seance {
    user_agent: string;
    ip: string;

    public constructor(user_agent: string, ip: string) {
        this.user_agent = user_agent;
        this.ip = ip;
    }
}
