import { DispensingEpisodeDTO, DispensingQueueState } from './types.js';

export class DispensingWorkspace {
  private activeQueue: DispensingEpisodeDTO[] = [];
  private selectedEpisode: DispensingEpisodeDTO | null = null;

  setQueue(episodes: DispensingEpisodeDTO[]): void {
    this.activeQueue = episodes;
  }

  filterQueue(state: DispensingQueueState | 'ALL'): DispensingEpisodeDTO[] {
    if (state === 'ALL') {
      return this.activeQueue;
    }
    return this.activeQueue.filter((ep) => ep.status === state);
  }

  selectEpisode(episodeId: string): DispensingEpisodeDTO | null {
    const found = this.activeQueue.find((ep) => ep.id === episodeId);
    if (found) {
      this.selectedEpisode = found;
    }
    return this.selectedEpisode;
  }

  getSelectedEpisode(): DispensingEpisodeDTO | null {
    return this.selectedEpisode;
  }
}
